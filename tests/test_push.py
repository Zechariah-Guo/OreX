"""Tests for opt-in Web Push: schema, endpoints, presence, sending, dedup, settings card.

pywebpush.webpush is always mocked, so no test touches the network. The sender
thread is switched off and the queue is drained on the test thread.
"""

import importlib.util
import os
import re
import sqlite3
import threading
from unittest import mock

import pytest
import pywebpush

from app import push
from app.models import create_notification, delete_account, reset_account
from conftest import get_csrf_token, login_user, register_user

SRC_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'src')
ENDPOINT_A = 'https://push.example.test/send/aaa'
ENDPOINT_B = 'https://push.example.test/send/bbb'
KEYS = {'p256dh': 'BPublicKeyValue', 'auth': 'authSecretValue'}


class Clock:
    """Stand-in for the time module inside app.push and app.routes.push."""

    def __init__(self, now=1_000_000.0):
        self.now = now

    def time(self):
        return self.now


@pytest.fixture()
def clock(monkeypatch):
    fake = Clock()
    monkeypatch.setattr('app.push.time', fake)
    monkeypatch.setattr('app.routes.push.time', fake)
    return fake


@pytest.fixture()
def vapid(app, monkeypatch):
    monkeypatch.setitem(app.config, 'VAPID_PUBLIC_KEY', 'BTestPublicKey')
    monkeypatch.setitem(app.config, 'VAPID_PRIVATE_KEY', 'test-private-key-never-logged')
    monkeypatch.setitem(app.config, 'VAPID_SUBJECT', 'mailto:owner@example.test')


@pytest.fixture(autouse=True)
def sync_sender(monkeypatch):
    """No sender thread; tests call push.drain(). Start from an empty queue."""
    monkeypatch.setattr(push, '_worker_enabled', False)
    while not push._queue.empty():
        push._queue.get_nowait()


@pytest.fixture()
def webpush_mock():
    with mock.patch('pywebpush.webpush') as fake:
        yield fake


def raw_db(app):
    conn = sqlite3.connect(app.config['DATABASE_PATH'], timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys=ON')
    return conn


def user_id(app, username):
    conn = raw_db(app)
    try:
        return conn.execute('SELECT id FROM users WHERE username = ?', (username,)).fetchone()['id']
    finally:
        conn.close()


def csrf_headers(client):
    return {'X-CSRFToken': get_csrf_token(client.get('/settings'))}


def post_json(client, url, body, headers=None):
    return client.post(url, json=body, headers=headers if headers is not None else csrf_headers(client))


def subscribe(client, endpoint=ENDPOINT_A):
    return post_json(client, '/push/subscribe', {'endpoint': endpoint, 'keys': KEYS})


def second_client(app, name='TestUser2'):
    other = app.test_client()
    register_user(other, name, 'Password123!')
    return other


def make_notification(app, uid, category='stop_loss', message='Stop Loss triggered: sold 3 Coal at $5.00'):
    with app.app_context():
        return create_notification(uid, category, message, target_url='/history')


def sweep(app, now=None):
    conn = raw_db(app)
    try:
        return push.sweep_pending_pushes(conn, app.config, app.config['DATABASE_PATH'], now)
    finally:
        conn.close()


def subscription_count(app, uid=None):
    conn = raw_db(app)
    try:
        if uid is None:
            return conn.execute('SELECT COUNT(*) FROM push_subscriptions').fetchone()[0]
        return conn.execute('SELECT COUNT(*) FROM push_subscriptions WHERE user_id = ?', (uid,)).fetchone()[0]
    finally:
        conn.close()


# --- Schema ------------------------------------------------------------------

class TestSchema:

    def test_schema_is_idempotent_and_creates_push_tables(self, app):
        schema = open(os.path.join(SRC_DIR, 'schema.sql')).read()
        conn = sqlite3.connect(app.config['DATABASE_PATH'])
        conn.executescript(schema)
        conn.executescript(schema)
        names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        cols = {r[1] for r in conn.execute('PRAGMA table_info(push_subscriptions)')}
        conn.close()
        assert {'push_subscriptions', 'push_settings', 'notification_pushes'} <= names
        assert {'user_id', 'endpoint', 'p256dh', 'auth', 'user_agent', 'created_at', 'last_success_at'} <= cols


# --- Category mapping ------------------------------------------------------------

class TestCategoryMapping:

    @pytest.mark.parametrize('category,group', [
        ('stop_loss', 'stop_loss'), ('take_profit', 'take_profit'), ('liquidation', 'liquidation'),
        ('bonus', 'bonus'), ('advancement', 'achievement'), ('achievement', 'achievement'),
    ])
    def test_mapped_categories(self, category, group):
        assert push.CATEGORY_GROUPS[category] == group

    def test_unmapped_category_gets_no_push(self, app, vapid, authenticated_client, clock, webpush_mock):
        uid = user_id(app, 'TestUser1')
        subscribe(authenticated_client)
        make_notification(app, uid, category='system', message='Something else')
        assert sweep(app, clock.now) == 0

    def test_payload_uses_message_url_and_tag(self):
        body = json_loads(push.build_payload(7, 'liquidation', 'x ' * 200, '/inbox?selected=7'))
        assert body['title'] == 'Position liquidated'
        assert body['url'] == '/inbox?selected=7'
        assert body['tag'] == 'orex-notification-7'
        assert body['category'] == 'liquidation'
        assert len(body['body']) <= push.MAX_BODY_CHARS


def json_loads(text):
    import json
    return json.loads(text)


# --- Endpoints -----------------------------------------------------------------------

class TestEndpoints:

    @pytest.mark.parametrize('url,body', [
        ('/push/subscribe', {'endpoint': ENDPOINT_A, 'keys': KEYS}),
        ('/push/unsubscribe', {'endpoint': ENDPOINT_A}),
        ('/push/preferences', {'take_profit': False}),
        ('/push/test', {}),
    ])
    def test_require_login(self, client, url, body):
        token = get_csrf_token(client.get('/login'))
        resp = client.post(url, json=body, headers={'X-CSRFToken': token})
        assert resp.status_code == 302 and '/login' in resp.headers['Location']

    @pytest.mark.parametrize('url,body', [
        ('/push/subscribe', {'endpoint': ENDPOINT_A, 'keys': KEYS}),
        ('/push/unsubscribe', {'endpoint': ENDPOINT_A}),
        ('/push/preferences', {'take_profit': False}),
        ('/push/test', {}),
    ])
    def test_require_csrf(self, authenticated_client, vapid, url, body):
        assert authenticated_client.post(url, json=body).status_code == 400

    def test_subscribe_stores_for_current_user_and_upserts(self, app, vapid, authenticated_client):
        uid = user_id(app, 'TestUser1')
        assert subscribe(authenticated_client).status_code == 200
        assert subscribe(authenticated_client).status_code == 200
        assert subscription_count(app, uid) == 1

    def test_subscribe_rejects_bad_input(self, vapid, authenticated_client):
        assert post_json(authenticated_client, '/push/subscribe', {'endpoint': 'http://x', 'keys': KEYS}).status_code == 400
        assert post_json(authenticated_client, '/push/subscribe', {'endpoint': ENDPOINT_A}).status_code == 400

    def test_endpoint_moves_to_the_new_account(self, app, vapid, authenticated_client):
        subscribe(authenticated_client)
        other = second_client(app)
        subscribe(other)
        assert subscription_count(app, user_id(app, 'TestUser1')) == 0
        assert subscription_count(app, user_id(app, 'TestUser2')) == 1

    def test_unsubscribe_only_removes_own(self, app, vapid, authenticated_client):
        subscribe(authenticated_client)
        other = second_client(app)
        resp = post_json(other, '/push/unsubscribe', {'endpoint': ENDPOINT_A})
        assert resp.get_json()['removed'] is False
        assert subscription_count(app) == 1
        resp = post_json(authenticated_client, '/push/unsubscribe', {'endpoint': ENDPOINT_A})
        assert resp.get_json()['removed'] is True
        assert subscription_count(app) == 0

    def test_preferences_default_on_save_and_scope(self, app, vapid, authenticated_client):
        html = authenticated_client.get('/settings').data.decode('utf-8')
        assert len(re.findall(r'data-push-group="[a-z_]+"\s+checked', html)) == 5
        resp = post_json(authenticated_client, '/push/preferences', {'take_profit': False, 'bonus': False})
        assert resp.get_json()['preferences'] == {
            'take_profit': False, 'stop_loss': True, 'liquidation': True, 'bonus': False, 'achievement': True}
        html = authenticated_client.get('/settings').data.decode('utf-8')
        assert len(re.findall(r'data-push-group="[a-z_]+"\s+checked', html)) == 3
        other = second_client(app)
        assert 'checked' in other.get('/settings').data.decode('utf-8').split('data-push-group="take_profit"')[1][:80]

    def test_preferences_reject_junk(self, authenticated_client):
        assert post_json(authenticated_client, '/push/preferences', {'nope': True}).status_code == 400
        assert post_json(authenticated_client, '/push/preferences', {'take_profit': 'yes'}).status_code == 400
        # the old combined key is gone, and one unknown key rejects the whole request
        assert post_json(authenticated_client, '/push/preferences', {'sltp': False}).status_code == 400
        assert post_json(authenticated_client, '/push/preferences', {'bonus': False, 'nope': True}).status_code == 400
        assert post_json(authenticated_client, '/push/preferences', {}).status_code == 400
        assert authenticated_client.get('/settings').data.decode('utf-8').count('data-push-group') >= 5

    def test_test_push_goes_to_own_devices_only_and_is_rate_limited(
            self, app, vapid, authenticated_client, clock, webpush_mock):
        subscribe(authenticated_client)
        other = second_client(app)
        subscribe(other, ENDPOINT_B)
        resp = post_json(authenticated_client, '/push/test', {})
        assert resp.status_code == 200 and resp.get_json()['queued'] == 1
        assert push.drain() == 1
        assert webpush_mock.call_args.kwargs['subscription_info']['endpoint'] == ENDPOINT_A
        assert post_json(authenticated_client, '/push/test', {}).status_code == 429
        clock.now += 31
        assert post_json(authenticated_client, '/push/test', {}).status_code == 200

    def test_test_push_without_subscription(self, vapid, authenticated_client):
        assert post_json(authenticated_client, '/push/test', {}).status_code == 400

    def test_config_endpoint(self, vapid, authenticated_client, client):
        data = authenticated_client.get('/push/config').get_json()
        assert data['configured'] is True and data['key'] == 'BTestPublicKey' and data['csrf']
        anon = client.application.test_client().get('/push/config').get_json()
        assert anon['configured'] is True and 'csrf' not in anon


# --- Presence ----------------------------------------------------------------------------

class TestPresence:

    def test_visible_polls_update_hidden_polls_do_not(self, app, vapid, authenticated_client, clock):
        uid = user_id(app, 'TestUser1')
        subscribe(authenticated_client)
        conn = raw_db(app)
        assert push.is_present(conn, uid, clock.now) is False
        authenticated_client.get('/inbox/poll?visible=0')
        assert push.is_present(conn, uid, clock.now) is False
        authenticated_client.get('/inbox/poll?visible=1')
        assert push.is_present(conn, uid, clock.now) is True
        clock.now += 59
        assert push.is_present(conn, uid, clock.now) is True
        clock.now += 2
        assert push.is_present(conn, uid, clock.now) is False
        authenticated_client.get('/inbox/poll?visible=0')
        assert push.is_present(conn, uid, clock.now) is False
        conn.close()

    def test_presence_write_is_throttled(self, app, vapid, authenticated_client, clock):
        uid = user_id(app, 'TestUser1')
        subscribe(authenticated_client)
        conn = raw_db(app)
        assert push.record_visible_poll(conn, uid, clock.now) is True
        assert push.record_visible_poll(conn, uid, clock.now + 10) is False
        assert push.record_visible_poll(conn, uid, clock.now + 16) is True
        conn.close()

    def test_players_without_a_subscription_are_not_tracked(self, app, authenticated_client, clock):
        authenticated_client.get('/inbox/poll?visible=1')
        conn = raw_db(app)
        assert conn.execute('SELECT COUNT(*) FROM push_settings').fetchone()[0] == 0
        assert conn.execute('SELECT COUNT(*) FROM push_presence').fetchone()[0] == 0
        conn.close()


# --- Instant "away" beacon ---------------------------------------------------------------

def away(client, client_id='pageA', token=None):
    """POST /push/away the way navigator.sendBeacon does: form fields, no headers."""
    data = {'client_id': client_id}
    data['csrf_token'] = get_csrf_token(client.get('/settings')) if token is None else token
    return client.post('/push/away', data=data)


class TestAwayBeacon:

    def test_beacon_makes_the_player_away_at_once(self, app, vapid, authenticated_client, clock, webpush_mock):
        uid = user_id(app, 'TestUser1')
        subscribe(authenticated_client)
        conn = raw_db(app)
        authenticated_client.get('/inbox/poll?visible=1&c=pageA')
        assert push.is_present(conn, uid, clock.now) is True
        assert away(authenticated_client).status_code == 204
        clock.now += 1
        assert push.is_present(conn, uid, clock.now) is False
        make_notification(app, uid)
        assert sweep(app, clock.now) == 1
        assert push.drain() == 1
        conn.close()

    def test_visible_poll_after_the_beacon_is_present_again_without_waiting(
            self, app, vapid, authenticated_client, clock):
        uid = user_id(app, 'TestUser1')
        subscribe(authenticated_client)
        conn = raw_db(app)
        authenticated_client.get('/inbox/poll?visible=1&c=pageA')
        away(authenticated_client)
        clock.now += 2                       # inside the 15 second write throttle
        authenticated_client.get('/inbox/poll?visible=1&c=pageA')
        assert push.is_present(conn, uid, clock.now) is True
        conn.close()

    def test_another_visible_device_keeps_the_player_present(
            self, app, vapid, authenticated_client, clock, webpush_mock):
        uid = user_id(app, 'TestUser1')
        subscribe(authenticated_client)
        conn = raw_db(app)
        authenticated_client.get('/inbox/poll?visible=1&c=phone')
        authenticated_client.get('/inbox/poll?visible=1&c=laptop')
        away(authenticated_client, 'phone')
        make_notification(app, uid)
        assert push.is_present(conn, uid, clock.now) is True
        assert sweep(app, clock.now) == 0
        away(authenticated_client, 'laptop')
        assert push.is_present(conn, uid, clock.now) is False
        assert sweep(app, clock.now) == 1
        conn.close()

    def test_one_device_going_quiet_does_not_end_the_others(self, app, vapid, authenticated_client, clock):
        uid = user_id(app, 'TestUser1')
        subscribe(authenticated_client)
        conn = raw_db(app)
        authenticated_client.get('/inbox/poll?visible=1&c=phone')      # then the phone dies
        clock.now += 50
        authenticated_client.get('/inbox/poll?visible=1&c=laptop')
        clock.now += 30                                                 # phone is 80 s old, laptop 30 s
        assert push.is_present(conn, uid, clock.now) is True
        clock.now += 31
        assert push.is_present(conn, uid, clock.now) is False
        conn.close()

    def test_without_a_beacon_the_sixty_second_fallback_still_applies(
            self, app, vapid, authenticated_client, clock, webpush_mock):
        uid = user_id(app, 'TestUser1')
        subscribe(authenticated_client)
        authenticated_client.get('/inbox/poll?visible=1&c=pageA')
        make_notification(app, uid)
        clock.now += 59
        assert sweep(app, clock.now) == 0
        clock.now += 2
        assert sweep(app, clock.now) == 1

    def test_beacon_only_affects_the_callers_own_account(self, app, vapid, authenticated_client, clock):
        uid = user_id(app, 'TestUser1')
        subscribe(authenticated_client)
        authenticated_client.get('/inbox/poll?visible=1&c=pageA')
        other = second_client(app)
        assert away(other, 'pageA').status_code == 204
        conn = raw_db(app)
        assert push.is_present(conn, uid, clock.now) is True
        conn.close()

    def test_requires_login_and_does_not_flash(self, client):
        token = get_csrf_token(client.get('/login'))
        resp = client.post('/push/away', data={'client_id': 'pageA', 'csrf_token': token})
        assert resp.status_code == 401
        with client.session_transaction() as sess:
            assert not sess.get('_flashes')

    def test_requires_csrf(self, app, vapid, authenticated_client, clock):
        uid = user_id(app, 'TestUser1')
        subscribe(authenticated_client)
        authenticated_client.get('/inbox/poll?visible=1&c=pageA')
        assert authenticated_client.post('/push/away', data={'client_id': 'pageA'}).status_code == 400
        assert away(authenticated_client, token='forged').status_code == 400
        conn = raw_db(app)
        assert push.is_present(conn, uid, clock.now) is True
        conn.close()

    def test_malformed_client_id_is_treated_as_none(self, app, vapid, authenticated_client, clock):
        uid = user_id(app, 'TestUser1')
        subscribe(authenticated_client)
        authenticated_client.get('/inbox/poll?visible=1&c=' + 'x' * 200)
        authenticated_client.get('/inbox/poll?visible=1&c=bad%20id')
        conn = raw_db(app)
        ids = [r[0] for r in conn.execute('SELECT client_id FROM push_presence WHERE user_id = ?', (uid,))]
        conn.close()
        assert ids == ['']
        assert away(authenticated_client, 'bad id').status_code == 204

    def test_poll_hands_out_a_fresh_token_only_for_visible_polls(self, authenticated_client):
        assert authenticated_client.get('/inbox/poll?visible=1&c=pageA').get_json()['csrf']
        assert 'csrf' not in authenticated_client.get('/inbox/poll?visible=0&c=pageA').get_json()


# --- Sending -----------------------------------------------------------------------------

class TestSending:

    def _setup(self, app, client):
        uid = user_id(app, 'TestUser1')
        subscribe(client)
        return uid

    def test_away_player_gets_one_push(self, app, vapid, authenticated_client, clock, webpush_mock):
        uid = self._setup(app, authenticated_client)
        nid = make_notification(app, uid)
        assert sweep(app, clock.now) == 1
        assert sweep(app, clock.now) == 0
        assert push.drain() == 1
        webpush_mock.assert_called_once()
        kwargs = webpush_mock.call_args.kwargs
        assert kwargs['subscription_info']['endpoint'] == ENDPOINT_A
        assert kwargs['timeout'] == push.SEND_TIMEOUT_SECONDS
        payload = json_loads(kwargs['data'])
        assert payload['url'] == f'/inbox?selected={nid}'
        assert payload['body'].startswith('Stop Loss triggered')

    def test_not_sent_to_suspended_player(self, app, vapid, authenticated_client, clock, webpush_mock):
        uid = self._setup(app, authenticated_client)
        make_notification(app, uid)
        conn = raw_db(app)
        conn.execute("UPDATE users SET suspended_at = '2024-01-01T00:00:00' WHERE id = ?", (uid,))
        conn.commit()
        conn.close()
        assert sweep(app, clock.now) == 0
        webpush_mock.assert_not_called()

    def test_not_sent_when_present(self, app, vapid, authenticated_client, clock, webpush_mock):
        uid = self._setup(app, authenticated_client)
        authenticated_client.get('/inbox/poll?visible=1')
        make_notification(app, uid)
        assert sweep(app, clock.now) == 0
        clock.now += 61
        assert sweep(app, clock.now) == 1

    def test_not_sent_when_category_off(self, app, vapid, authenticated_client, clock, webpush_mock):
        uid = self._setup(app, authenticated_client)
        post_json(authenticated_client, '/push/preferences', {'stop_loss': False})
        make_notification(app, uid)
        make_notification(app, uid, 'liquidation', 'Position liquidated: 2 Coal')
        assert sweep(app, clock.now) == 1
        push.drain()
        assert json_loads(webpush_mock.call_args.kwargs['data'])['category'] == 'liquidation'

    def test_take_profit_and_stop_loss_are_independent(self, app, vapid, authenticated_client, clock, webpush_mock):
        uid = self._setup(app, authenticated_client)
        post_json(authenticated_client, '/push/preferences', {'take_profit': False})
        make_notification(app, uid, 'take_profit', 'Take Profit triggered: 1 Coal')
        assert sweep(app, clock.now) == 0
        make_notification(app, uid, 'stop_loss', 'Stop Loss triggered: 1 Coal')
        assert sweep(app, clock.now) == 1
        push.drain()
        assert json_loads(webpush_mock.call_args.kwargs['data'])['category'] == 'stop_loss'
        post_json(authenticated_client, '/push/preferences', {'take_profit': True, 'stop_loss': False})
        make_notification(app, uid, 'stop_loss', 'Stop Loss triggered: 2 Coal')
        # the earlier take profit (skipped while off) is now sent; the new stop loss is not
        assert sweep(app, clock.now) == 1
        push.drain()
        assert json_loads(webpush_mock.call_args.kwargs['data'])['category'] == 'take_profit'
        assert sweep(app, clock.now) == 0

    def test_both_split_groups_are_high_urgency(self):
        assert push.urgency_for('take_profit') == 'high' and push.urgency_for('stop_loss') == 'high'

    def test_not_sent_without_subscription(self, app, vapid, authenticated_client, clock, webpush_mock):
        make_notification(app, user_id(app, 'TestUser1'))
        assert sweep(app, clock.now) == 0
        assert push.drain() == 0

    def test_old_notifications_are_not_pushed(self, app, vapid, authenticated_client, clock, webpush_mock):
        uid = self._setup(app, authenticated_client)
        make_notification(app, uid)
        conn = raw_db(app)
        conn.execute("UPDATE notifications SET created_at = datetime('now', 'localtime', '-10 minutes')")
        conn.commit()
        conn.close()
        assert sweep(app, clock.now) == 0

    def test_already_toasted_is_not_pushed(self, app, vapid, authenticated_client, clock, webpush_mock):
        uid = self._setup(app, authenticated_client)
        make_notification(app, uid)
        authenticated_client.get('/inbox/poll')
        assert sweep(app, clock.now) == 0

    def test_pushed_notification_is_not_toasted_but_stays_unread(
            self, app, vapid, authenticated_client, clock, webpush_mock):
        uid = self._setup(app, authenticated_client)
        nid = make_notification(app, uid)
        sweep(app, clock.now)
        data = authenticated_client.get('/inbox/poll?visible=1').get_json()
        assert nid not in [n['id'] for n in data['notifications']]
        assert data['has_unread'] is True
        assert f'/inbox?selected={nid}' in authenticated_client.get('/inbox?filter=unread').data.decode('utf-8')

    def test_hidden_poll_keeps_toasts_for_the_return(self, app, authenticated_client):
        nid = make_notification(app, user_id(app, 'TestUser1'))
        assert authenticated_client.get('/inbox/poll?visible=0').get_json()['notifications'] == []
        shown = authenticated_client.get('/inbox/poll?visible=1').get_json()['notifications']
        assert nid in [n['id'] for n in shown]

    def test_poll_without_visibility_param_still_toasts(self, app, authenticated_client):
        nid = make_notification(app, user_id(app, 'TestUser1'))
        shown = authenticated_client.get('/inbox/poll').get_json()['notifications']
        assert nid in [n['id'] for n in shown]

    def test_gone_subscription_is_deleted(self, app, vapid, authenticated_client, clock, webpush_mock):
        uid = self._setup(app, authenticated_client)
        make_notification(app, uid)
        sweep(app, clock.now)
        webpush_mock.side_effect = pywebpush.WebPushException('gone', response=mock.Mock(status_code=410))
        push.drain()
        assert subscription_count(app, uid) == 0

    def test_other_errors_keep_the_subscription(self, app, vapid, authenticated_client, clock, webpush_mock):
        uid = self._setup(app, authenticated_client)
        make_notification(app, uid)
        sweep(app, clock.now)
        webpush_mock.side_effect = pywebpush.WebPushException('busy', response=mock.Mock(status_code=503))
        push.drain()
        assert subscription_count(app, uid) == 1

    def test_success_records_last_success(self, app, vapid, authenticated_client, clock, webpush_mock):
        uid = self._setup(app, authenticated_client)
        make_notification(app, uid)
        sweep(app, clock.now)
        push.drain()
        conn = raw_db(app)
        row = conn.execute('SELECT last_success_at FROM push_subscriptions WHERE user_id = ?', (uid,)).fetchone()
        conn.close()
        assert row['last_success_at'] is not None

    def test_concurrent_attempts_send_once(self, app, vapid, authenticated_client, clock, webpush_mock):
        uid = self._setup(app, authenticated_client)
        nid = make_notification(app, uid)
        barrier = threading.Barrier(2)
        results = []

        def attempt():
            conn = raw_db(app)
            try:
                barrier.wait()
                results.append(push.claim_notification(conn, nid))
            finally:
                conn.close()

        threads = [threading.Thread(target=attempt) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert sorted(results) == [False, True]

    def test_two_sweeps_in_parallel_send_once(self, app, vapid, authenticated_client, clock, webpush_mock):
        uid = self._setup(app, authenticated_client)
        make_notification(app, uid)
        barrier = threading.Barrier(2)
        claimed = []

        def attempt():
            conn = raw_db(app)
            try:
                barrier.wait()
                claimed.append(push.sweep_pending_pushes(
                    conn, app.config, app.config['DATABASE_PATH'], clock.now))
            finally:
                conn.close()

        threads = [threading.Thread(target=attempt) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert sum(claimed) == 1
        assert push.drain() == 1
        webpush_mock.assert_called_once()

    def test_engine_cycle_sweeps(self, app, vapid, authenticated_client, clock, webpush_mock, monkeypatch):
        monkeypatch.setattr(push, 'schedule_bonus_reminders', lambda app, db: None)
        uid = self._setup(app, authenticated_client)
        make_notification(app, uid)
        conn = raw_db(app)
        push.process_push_cycle(app, conn)
        conn.close()
        assert push.drain() == 1


# --- Not configured -------------------------------------------------------------------------------

class TestNotConfigured:

    @pytest.fixture(autouse=True)
    def _clear_keys(self, app, monkeypatch):
        for key in ('VAPID_PUBLIC_KEY', 'VAPID_PRIVATE_KEY', 'VAPID_SUBJECT'):
            monkeypatch.setitem(app.config, key, '')

    def test_endpoints_answer_503(self, authenticated_client):
        assert subscribe(authenticated_client).status_code == 503
        assert post_json(authenticated_client, '/push/test', {}).status_code == 503
        assert authenticated_client.get('/push/config').get_json()['configured'] is False

    def test_sweep_and_cycle_do_nothing(self, app, authenticated_client, webpush_mock):
        make_notification(app, user_id(app, 'TestUser1'))
        assert sweep(app) == 0
        conn = raw_db(app)
        push.process_push_cycle(app, conn)
        conn.close()
        webpush_mock.assert_not_called()

    def test_settings_card_says_not_configured(self, authenticated_client):
        html = authenticated_client.get('/settings').data.decode('utf-8')
        assert 'data-configured="false"' in html
        assert 'Notifications are not configured on this server.' in html

    def test_subject_must_be_a_url(self, app, monkeypatch):
        monkeypatch.setitem(app.config, 'VAPID_PUBLIC_KEY', 'k')
        monkeypatch.setitem(app.config, 'VAPID_PRIVATE_KEY', 'p')
        monkeypatch.setitem(app.config, 'VAPID_SUBJECT', 'owner@example.test')
        assert push.is_configured(app.config) is False


# --- Account deletion and reset ------------------------------------------------------------------

class TestAccountCleanup:

    def test_delete_account_removes_subscriptions(self, app, vapid, authenticated_client):
        uid = user_id(app, 'TestUser1')
        subscribe(authenticated_client)
        with app.app_context():
            delete_account(uid)
        assert subscription_count(app) == 0

    def test_reset_account_keeps_subscriptions(self, app, vapid, authenticated_client):
        uid = user_id(app, 'TestUser1')
        subscribe(authenticated_client)
        with app.app_context():
            reset_account(uid)
        assert subscription_count(app) == 1


# --- Daily bonus scheduling -----------------------------------------------------------------------

class TestBonusScheduling:

    def _bonus_count(self, app, uid):
        conn = raw_db(app)
        try:
            return conn.execute(
                "SELECT COUNT(*) FROM notifications WHERE user_id = ? AND category = 'bonus'", (uid,)
            ).fetchone()[0]
        finally:
            conn.close()

    def test_creates_the_existing_reminder_once_for_subscribed_players(
            self, app, vapid, authenticated_client):
        uid = user_id(app, 'TestUser1')
        subscribe(authenticated_client)
        conn = raw_db(app)
        push.schedule_bonus_reminders(app, conn)
        push.schedule_bonus_reminders(app, conn)
        conn.close()
        assert self._bonus_count(app, uid) == 1

    def test_skips_players_without_subscription_or_with_switch_off(self, app, vapid, authenticated_client):
        uid = user_id(app, 'TestUser1')
        conn = raw_db(app)
        push.schedule_bonus_reminders(app, conn)
        assert self._bonus_count(app, uid) == 0
        subscribe(authenticated_client)
        post_json(authenticated_client, '/push/preferences', {'bonus': False})
        push.schedule_bonus_reminders(app, conn)
        conn.close()
        assert self._bonus_count(app, uid) == 0

    def test_skips_suspended_players(self, app, vapid, authenticated_client):
        uid = user_id(app, 'TestUser1')
        subscribe(authenticated_client)
        conn = raw_db(app)
        conn.execute("UPDATE users SET suspended_at = '2024-01-01T00:00:00' WHERE id = ?", (uid,))
        conn.commit()
        push.schedule_bonus_reminders(app, conn)
        conn.close()
        assert self._bonus_count(app, uid) == 0

    def test_reminder_is_pushed_to_an_away_player(self, app, vapid, authenticated_client, clock, webpush_mock):
        subscribe(authenticated_client)
        conn = raw_db(app)
        push.schedule_bonus_reminders(app, conn)
        conn.close()
        assert sweep(app, clock.now) == 1
        push.drain()
        assert json_loads(webpush_mock.call_args.kwargs['data'])['category'] == 'bonus'


# --- Static pieces ------------------------------------------------------------------------------------

class TestServiceWorkerAndPage:
    # What sw.js, push.js and notifications.js do in a browser is checked in test_push_browser.py

    def test_settings_card_sits_under_install_card_and_is_hidden(self, vapid, authenticated_client):
        html = authenticated_client.get('/settings').data.decode('utf-8')
        # always rendered (never hidden): the device switch starts disabled and push.js enables it
        card = re.search(r'<div class="settings-card push-card" id="push-card"\s+data-configured', html)
        assert card
        assert re.search(r'<input type="checkbox" role="switch" id="push-device-switch" disabled>', html)
        assert re.search(r'id="push-unsupported" hidden>This browser can\'t show notifications\. '
                         r'Try Chrome, Edge, Firefox or Safari\.</p>', html)
        assert 'id="settings-nav-device"' not in html
        assert (html.index('id="install-card"') < html.index('id="push-card"')
                < html.index('id="appearance"'))
        between = html[html.index('id="install-card"'):html.index('id="push-card"')]
        assert between.count('<div class="settings-card') == 1  # only the push card's own opening tag
        assert 'Enable push notifications for this device' in html
        assert 'Send a test' in html and 'Send test notification' not in html
        assert 'Add OreX to your Home Screen to get notifications (iOS 16.4 or later).' in html
        assert 'data-configured="true"' in html
        # the old buttons and device count are gone
        assert 'push-toggle-btn' not in html and 'push-summary' not in html
        assert 'Disable on this device' not in html
        card_html = html[html.index('id="push-card"'):html.index('id="appearance"')]
        # the device switch is for this device, the category switches for all of the player's devices
        assert 'for this device only' in card_html and 'all of your devices' in card_html
        # the device switch is a native checkbox switch; the categories sit in a block that is hidden until the device is on
        assert re.search(r'<input type="checkbox" role="switch" id="push-device-switch" disabled>', card_html)
        assert re.search(r'<div id="push-prefs" hidden>', card_html)
        # five category switches, in order, with consistent labels
        keys = re.findall(r'<input type="checkbox" role="switch" id="push-pref-([a-z_]+)" data-push-group="\1"', card_html)
        assert keys == ['take_profit', 'stop_loss', 'liquidation', 'bonus', 'achievement']
        labels = re.findall(r'<span class="push-card__row-label">([^<]+)</span>', card_html)
        assert labels == ['Take profit', 'Stop loss', 'Liquidations', 'Daily bonus', 'Achievements']
        # same icon classes as the inbox list
        for css in ('flash--take-profit', 'flash--stop-loss', 'flash--liquidation', 'flash--bonus', 'flash--achievement'):
            assert f'inbox__list-item-icon push-card__icon {css}' in card_html
        # the test action lives in a quiet footer after the list, inside the hidden block
        prefs = card_html[card_html.index('id="push-prefs"'):]
        assert prefs.index('push-card__list') < prefs.index('push-card__footer') < prefs.index('id="push-test-btn"')
        assert 'push-footer-state' in prefs and 'push-test-status' in prefs
        assert 'push-footer-devices' not in prefs  # the device count is part of the one status line
        assert 'btn btn--secondary push-card__btn' not in card_html


class TestDeviceStatusAndSelfHeal:
    """The server row for a device can vanish while the browser keeps its
    subscription; the page re-posts it and the card follows the server."""

    def test_status_reflects_this_device_and_device_count(self, app, vapid, authenticated_client):
        url = '/push/status?endpoint='
        assert authenticated_client.get(url + ENDPOINT_A).get_json() == {'subscribed': False, 'devices': 0}
        subscribe(authenticated_client, ENDPOINT_A)
        subscribe(authenticated_client, ENDPOINT_B)
        assert authenticated_client.get(url + ENDPOINT_A).get_json() == {'subscribed': True, 'devices': 2}
        assert authenticated_client.get('/push/status').get_json() == {'subscribed': False, 'devices': 2}

    def test_status_does_not_confirm_another_accounts_endpoint(self, app, vapid, authenticated_client):
        other = second_client(app)
        subscribe(other, ENDPOINT_B)
        data = authenticated_client.get('/push/status?endpoint=' + ENDPOINT_B).get_json()
        assert data == {'subscribed': False, 'devices': 0}

    def test_status_requires_login(self, client):
        resp = client.get('/push/status')
        assert resp.status_code == 302 and '/login' in resp.headers['Location']

    @pytest.mark.parametrize('cause', ['gone', 'pruned', 'moved'])
    def test_repost_restores_a_missing_row_and_reports_devices(
            self, app, vapid, authenticated_client, cause, webpush_mock, clock):
        uid = user_id(app, 'TestUser1')
        subscribe(authenticated_client, ENDPOINT_A)
        if cause == 'gone':
            make_notification(app, uid)
            webpush_mock.side_effect = pywebpush.WebPushException('gone', response=mock.Mock(status_code=410))
            sweep(app, clock.now)
            push.drain()
        elif cause == 'pruned':
            for i in range(push_route_limit()):
                subscribe(authenticated_client, f'https://push.example.test/send/n{i}')
        else:
            subscribe(second_client(app), ENDPOINT_A)
        assert authenticated_client.get('/push/status?endpoint=' + ENDPOINT_A).get_json()['subscribed'] is False
        resp = subscribe(authenticated_client, ENDPOINT_A)
        assert resp.status_code == 200 and resp.get_json()['subscribed'] is True and resp.get_json()['devices'] >= 1
        assert authenticated_client.get('/push/status?endpoint=' + ENDPOINT_A).get_json()['subscribed'] is True

    def test_subscribe_reports_device_count(self, vapid, authenticated_client):
        assert subscribe(authenticated_client, ENDPOINT_A).get_json()['devices'] == 1
        assert subscribe(authenticated_client, ENDPOINT_A).get_json()['devices'] == 1
        assert subscribe(authenticated_client, ENDPOINT_B).get_json()['devices'] == 2

    def test_per_device_test_sends_only_to_the_given_endpoint(
            self, app, vapid, authenticated_client, clock, webpush_mock):
        subscribe(authenticated_client, ENDPOINT_A)
        subscribe(authenticated_client, ENDPOINT_B)
        resp = post_json(authenticated_client, '/push/test', {'endpoint': ENDPOINT_B})
        assert resp.status_code == 200 and resp.get_json()['queued'] == 1
        push.drain()
        webpush_mock.assert_called_once()
        assert webpush_mock.call_args.kwargs['subscription_info']['endpoint'] == ENDPOINT_B

    def test_test_without_endpoint_sends_to_all_devices(
            self, app, vapid, authenticated_client, clock, webpush_mock):
        subscribe(authenticated_client, ENDPOINT_A)
        subscribe(authenticated_client, ENDPOINT_B)
        assert post_json(authenticated_client, '/push/test', {}).get_json()['queued'] == 2

    def test_per_device_test_rejects_another_accounts_endpoint(
            self, app, vapid, authenticated_client, clock, webpush_mock):
        subscribe(authenticated_client, ENDPOINT_A)
        subscribe(second_client(app), ENDPOINT_B)
        resp = post_json(authenticated_client, '/push/test', {'endpoint': ENDPOINT_B})
        assert resp.status_code == 400 and resp.get_json() == {'error': 'no_subscription'}
        assert push.drain() == 0
        # a rejected request does not use up the cooldown
        assert post_json(authenticated_client, '/push/test', {'endpoint': ENDPOINT_A}).status_code == 200

    def test_error_codes_are_json(self, app, vapid, authenticated_client, clock, webpush_mock):
        resp = post_json(authenticated_client, '/push/test', {'endpoint': ENDPOINT_A})
        assert resp.status_code == 400 and resp.get_json()['error'] == 'no_subscription'
        subscribe(authenticated_client, ENDPOINT_A)
        assert post_json(authenticated_client, '/push/test', {}).status_code == 200
        resp = post_json(authenticated_client, '/push/test', {})
        assert resp.status_code == 429 and resp.get_json()['error'] == 'too_soon'

    def test_missing_csrf_answers_html_not_json(self, vapid, authenticated_client):
        resp = authenticated_client.post('/push/test', json={})
        assert resp.status_code == 400 and not resp.is_json


def push_route_limit():
    from app.routes.push import MAX_SUBSCRIPTIONS_PER_USER
    return MAX_SUBSCRIPTIONS_PER_USER


class TestUrgencyAndRejections:

    def _setup(self, app, client):
        subscribe(client)
        return user_id(app, 'TestUser1')

    @pytest.mark.parametrize('category, expected', [
        ('stop_loss', 'high'), ('take_profit', 'high'), ('liquidation', 'high'),
        ('bonus', 'normal'), ('achievement', 'normal'), ('advancement', 'normal'),
    ])
    def test_urgency_per_category(self, app, vapid, authenticated_client, clock, webpush_mock,
                                  category, expected):
        uid = self._setup(app, authenticated_client)
        make_notification(app, uid, category, 'Something happened')
        sweep(app, clock.now)
        push.drain()
        kwargs = webpush_mock.call_args.kwargs
        assert kwargs['headers'] == {'Urgency': expected}
        assert kwargs['ttl'] == push.PUSH_TTL_SECONDS == 86400

    def test_test_push_is_high_urgency(self, app, vapid, authenticated_client, clock, webpush_mock):
        self._setup(app, authenticated_client)
        post_json(authenticated_client, '/push/test', {})
        push.drain()
        assert webpush_mock.call_args.kwargs['headers'] == {'Urgency': 'high'}

    @pytest.mark.parametrize('status, kept', [(403, 0), (404, 0), (410, 0), (500, 1), (429, 1)])
    def test_rejection_status_decides_whether_the_subscription_is_kept(
            self, app, vapid, authenticated_client, clock, webpush_mock, status, kept):
        uid = self._setup(app, authenticated_client)
        make_notification(app, uid)
        sweep(app, clock.now)
        webpush_mock.side_effect = pywebpush.WebPushException('no', response=mock.Mock(status_code=status))
        push.drain()
        assert subscription_count(app, uid) == kept

    def test_rejection_is_logged_with_status_and_host_but_not_the_endpoint(
            self, app, vapid, authenticated_client, clock, webpush_mock, caplog):
        uid = self._setup(app, authenticated_client)
        subscribe(authenticated_client, 'https://fcm.googleapis.com/fcm/send/secret-token')
        make_notification(app, uid)
        sweep(app, clock.now)
        webpush_mock.side_effect = pywebpush.WebPushException('no', response=mock.Mock(status_code=403))
        with caplog.at_level('WARNING', logger='app.push'):
            push.drain()
        text = caplog.text
        assert 'status 403' in text and 'fcm.googleapis.com' in text
        assert 'secret-token' not in text and 'fcm/send' not in text


class TestKeyScript:

    def test_generated_pair_loads_in_pywebpush(self):
        path = os.path.join(os.path.dirname(SRC_DIR), 'scripts', 'admin', 'generate_vapid_keys.py')
        spec = importlib.util.spec_from_file_location('generate_vapid_keys', path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        public_key, private_key = module.generate()
        from py_vapid import Vapid
        vapid_key = Vapid.from_string(private_key)
        assert vapid_key.public_key is not None
        assert len(public_key) == 87 and len(private_key) == 43


