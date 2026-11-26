"""Real-browser tests for Web Push on the page (push.js, notifications.js, sw.js).

Headless Chrome/Edge through Playwright, against the test app served over HTTP.
The browser's push service is replaced by a small fake (FAKE_PUSH below): a
headless browser cannot reach a real push service, and the fake also records
every permission request. Everything else is the real page code talking to the
real server routes, so these check what happens, not what the source says.

Skipped when no Chrome/Edge is installed. Deselect with: pytest -m "not browser"
"""

import base64
import sqlite3

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

from conftest import browser_login

pytestmark = pytest.mark.browser

# Stands in for the browser's push service. State lives in localStorage so a
# subscription survives reloads like a real one. window.__permissionRequests
# counts Notification.requestPermission calls on the current page.
FAKE_PUSH = """
(() => {
    if (!('PushManager' in window)) { return; }
    const KEY = 'fakePush';
    const load = () => { try { return JSON.parse(localStorage.getItem(KEY)) || {}; } catch (e) { return {}; } };
    const save = (s) => { try { localStorage.setItem(KEY, JSON.stringify(s)); } catch (e) {} };
    const toBytes = (b64) => Uint8Array.from(atob(b64), (c) => c.charCodeAt(0)).buffer;
    window.__permissionRequests = 0;
    Object.defineProperty(Notification, 'permission', {
        configurable: true, get: () => load().permission || 'default',
    });
    Notification.requestPermission = function () {
        window.__permissionRequests += 1;
        const s = load(); s.permission = 'granted'; save(s);
        return Promise.resolve('granted');
    };
    const makeSub = (s) => ({
        endpoint: s.endpoint,
        options: { applicationServerKey: s.key ? toBytes(s.key) : null },
        toJSON() { return { endpoint: s.endpoint, keys: { p256dh: 'BFakeP256dhKey', auth: 'fakeAuthSecret' } }; },
        unsubscribe() { const t = load(); delete t.endpoint; delete t.key; save(t); return Promise.resolve(true); },
    });
    PushManager.prototype.getSubscription = function () {
        const s = load();
        return Promise.resolve(s.endpoint ? makeSub(s) : null);
    };
    PushManager.prototype.subscribe = function (options) {
        const s = load();
        s.endpoint = 'https://push.example.test/send/' + Math.random().toString(36).slice(2);
        s.key = btoa(String.fromCharCode(...new Uint8Array(options.applicationServerKey)));
        save(s);
        return Promise.resolve(makeSub(s));
    };
})();
"""


def _public_key():
    """A real-format VAPID public key: base64url of an uncompressed P-256 point."""
    point = ec.generate_private_key(ec.SECP256R1()).public_key().public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    return base64.urlsafe_b64encode(point).rstrip(b'=').decode(), base64.b64encode(point).decode()


@pytest.fixture()
def vapid(app, monkeypatch):
    public_url, public_std = _public_key()
    monkeypatch.setitem(app.config, 'VAPID_PUBLIC_KEY', public_url)
    monkeypatch.setitem(app.config, 'VAPID_PRIVATE_KEY', 'browser-test-private-key')
    monkeypatch.setitem(app.config, 'VAPID_SUBJECT', 'mailto:owner@example.test')
    return public_std


@pytest.fixture()
def page(browser_context):
    browser_context.add_init_script(FAKE_PUSH)
    return browser_context.new_page()


def _rows(app, query, params=()):
    conn = sqlite3.connect(app.config['DATABASE_PATH'], timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        return conn.execute(query, params).fetchall()
    finally:
        conn.close()


def _wait_until(page, check, what, timeout=10):
    """Poll a Python check (e.g. a database query) while letting the page run."""
    for _ in range(int(timeout / 0.1)):
        if check():
            return
        page.wait_for_timeout(100)
    raise AssertionError(f'Timed out waiting for {what}')


def _open_settings(page, live_server):
    page.goto(live_server + '/settings')
    # push.js enables the switch once it has asked the server about this device
    page.wait_for_selector('#push-device-switch:not([disabled])', state='attached')   # styled switch: input is hidden
    page.wait_for_function("document.getElementById('push-device-switch').getAttribute('aria-busy') !== 'true'")


class TestTurningNotificationsOn:

    def test_permission_is_requested_only_by_the_device_switch(self, app, live_server, vapid, page):
        user_id = browser_login(page, live_server, app)
        assert page.evaluate('window.__permissionRequests') == 0       # dashboard: no prompt

        _open_settings(page, live_server)
        page.wait_for_timeout(300)
        assert page.evaluate('window.__permissionRequests') == 0       # settings load: no prompt
        assert not page.is_checked('#push-device-switch')

        page.evaluate("document.getElementById('push-device-switch').click()")
        page.wait_for_selector('#push-prefs:not([hidden])')
        assert page.evaluate('window.__permissionRequests') == 1
        assert page.text_content('#push-footer-state') == 'Notifications are on for this device'
        rows = _rows(app, 'SELECT endpoint FROM push_subscriptions WHERE user_id = ?', (user_id,))
        assert len(rows) == 1 and rows[0]['endpoint'].startswith('https://push.example.test/')

        # A reload asks the server again and shows it on, without another prompt
        _open_settings(page, live_server)
        assert page.is_checked('#push-device-switch')
        assert page.evaluate('window.__permissionRequests') == 0

    def test_turning_it_off_removes_the_server_row(self, app, live_server, vapid, page):
        user_id = browser_login(page, live_server, app)
        _open_settings(page, live_server)
        page.evaluate("document.getElementById('push-device-switch').click()")
        page.wait_for_selector('#push-prefs:not([hidden])')

        page.evaluate("document.getElementById('push-device-switch').click()")
        page.wait_for_selector('#push-prefs', state='hidden')
        assert not page.is_checked('#push-device-switch')
        assert _rows(app, 'SELECT 1 FROM push_subscriptions WHERE user_id = ?', (user_id,)) == []


class TestSelfHeal:
    """The server row can vanish while the browser keeps its subscription (account
    reset, pruned after a rejected push). Settings must notice and register it again."""

    def _browser_has_subscription(self, page, live_server, endpoint, key_b64, owner=None):
        page.goto(live_server + '/about')
        page.evaluate(
            "([endpoint, key, owner]) => { localStorage.setItem('fakePush', "
            "JSON.stringify({permission: 'granted', endpoint, key}));"
            " if (owner) { localStorage.setItem('orex-push-owner', owner); }"
            " else { localStorage.removeItem('orex-push-owner'); } }",
            [endpoint, key_b64, owner])

    def _browser_endpoint(self, page):
        return page.evaluate("(JSON.parse(localStorage.getItem('fakePush')) || {}).endpoint || null")

    def test_missing_server_row_is_restored_on_settings_load(self, app, live_server, vapid, page):
        user_id = browser_login(page, live_server, app)
        endpoint = 'https://push.example.test/send/kept-by-the-browser'
        self._browser_has_subscription(page, live_server, endpoint, vapid, owner=str(user_id))
        assert _rows(app, 'SELECT 1 FROM push_subscriptions') == []

        _open_settings(page, live_server)
        assert page.is_checked('#push-device-switch')
        assert page.text_content('#push-footer-state') == 'Notifications are on for this device'
        rows = _rows(app, 'SELECT endpoint FROM push_subscriptions WHERE user_id = ?', (user_id,))
        assert [r['endpoint'] for r in rows] == [endpoint]
        assert page.evaluate('window.__permissionRequests') == 0

    def test_subscription_made_with_an_old_server_key_is_replaced(self, app, live_server, vapid, page):
        user_id = browser_login(page, live_server, app)
        old_endpoint = 'https://push.example.test/send/old-key'
        _, other_key = _public_key()
        self._browser_has_subscription(page, live_server, old_endpoint, other_key, owner=str(user_id))

        _open_settings(page, live_server)
        assert page.is_checked('#push-device-switch')
        rows = _rows(app, 'SELECT endpoint FROM push_subscriptions WHERE user_id = ?', (user_id,))
        assert len(rows) == 1 and rows[0]['endpoint'] != old_endpoint
        assert page.evaluate("JSON.parse(localStorage.getItem('fakePush')).key") == vapid

    @pytest.mark.parametrize('where', ['settings', 'other page'])
    def test_subscription_left_by_another_account_is_dropped(self, app, live_server, vapid, page, where):
        user_id = browser_login(page, live_server, app)
        self._browser_has_subscription(page, live_server, 'https://push.example.test/send/someone-else',
                                       vapid, owner=str(user_id + 1000))
        if where == 'settings':
            _open_settings(page, live_server)
            assert not page.is_checked('#push-device-switch')
        else:
            page.evaluate("sessionStorage.removeItem('orex-push-healed')")
            page.goto(live_server + '/dashboard')
            page.wait_for_function("!(JSON.parse(localStorage.getItem('fakePush')) || {}).endpoint")
        assert self._browser_endpoint(page) is None
        assert page.evaluate("localStorage.getItem('orex-push-owner')") is None
        assert _rows(app, 'SELECT 1 FROM push_subscriptions') == []

    def test_unowned_subscription_is_kept_only_if_the_server_has_it_for_this_account(
            self, app, live_server, vapid, page):
        user_id = browser_login(page, live_server, app)
        endpoint = 'https://push.example.test/send/from-before-owners'
        self._browser_has_subscription(page, live_server, endpoint, vapid)
        conn = sqlite3.connect(app.config['DATABASE_PATH'])
        conn.execute("INSERT INTO push_subscriptions (user_id, endpoint, p256dh, auth) VALUES (?, ?, 'k', 'a')",
                     (user_id, endpoint))
        conn.commit()
        conn.close()
        _open_settings(page, live_server)
        assert page.is_checked('#push-device-switch')
        assert page.evaluate("localStorage.getItem('orex-push-owner')") == str(user_id)

        # Same unowned subscription, but the server has no row for it: dropped
        self._browser_has_subscription(page, live_server, endpoint + '-2', vapid)
        _open_settings(page, live_server)
        assert not page.is_checked('#push-device-switch')
        assert self._browser_endpoint(page) is None

    def test_session_ending_without_logout_does_not_pass_notifications_on(
            self, app, live_server, vapid, page, browser_context):
        browser_login(page, live_server, app)
        _open_settings(page, live_server)
        page.evaluate("document.getElementById('push-device-switch').click()")
        page.wait_for_selector('#push-prefs:not([hidden])')

        browser_context.clear_cookies()            # session expired: no logout click
        page.evaluate("sessionStorage.clear()")
        new_id = browser_login(page, live_server, app, username='NextPlayer')
        _open_settings(page, live_server)
        assert not page.is_checked('#push-device-switch')
        assert _rows(app, 'SELECT 1 FROM push_subscriptions WHERE user_id = ?', (new_id,)) == []


class TestDeleteAccount:
    """Deleting the account drops this browser's subscription, so the next account
    that signs in on the device does not inherit notifications."""

    def _browser_endpoint(self, page):
        return page.evaluate("(JSON.parse(localStorage.getItem('fakePush')) || {}).endpoint || null")

    def _submit_delete(self, page, live_server, typed):
        page.goto(live_server + '/settings/delete')
        page.fill('#confirmation', typed)
        with page.expect_navigation():
            page.click('button[type="submit"]')

    def test_next_account_on_the_device_starts_with_notifications_off(self, app, live_server, vapid, page):
        browser_login(page, live_server, app)
        _open_settings(page, live_server)
        page.evaluate("document.getElementById('push-device-switch').click()")
        page.wait_for_selector('#push-prefs:not([hidden])')
        assert self._browser_endpoint(page)

        # A rejected confirmation keeps the account and this device's subscription
        self._submit_delete(page, live_server, 'not-my-name')
        assert self._browser_endpoint(page)
        assert len(_rows(app, 'SELECT 1 FROM push_subscriptions')) == 1

        self._submit_delete(page, live_server, 'BrowserUser')
        assert page.url.rstrip('/') == live_server
        assert self._browser_endpoint(page) is None
        assert _rows(app, 'SELECT 1 FROM push_subscriptions') == []

        new_id = browser_login(page, live_server, app, username='NextPlayer')
        _open_settings(page, live_server)
        assert not page.is_checked('#push-device-switch')
        assert _rows(app, 'SELECT 1 FROM push_subscriptions WHERE user_id = ?', (new_id,)) == []


class TestPresence:
    """A visible page marks the player present; hiding it tells the server at once."""

    def test_hiding_the_page_sends_one_away_signal_and_showing_it_returns(self, app, live_server, vapid, page):
        user_id = browser_login(page, live_server, app)
        # Presence is only tracked for players with a subscription
        conn = sqlite3.connect(app.config['DATABASE_PATH'])
        conn.execute("INSERT INTO push_subscriptions (user_id, endpoint, p256dh, auth) VALUES (?, ?, 'k', 'a')",
                     (user_id, 'https://push.example.test/send/presence'))
        conn.commit()
        conn.close()

        away_requests = []
        page.on('request', lambda r: away_requests.append(r) if r.url.endswith('/push/away') else None)
        present = lambda: _rows(app, 'SELECT 1 FROM push_presence WHERE user_id = ?', (user_id,))

        page.goto(live_server + '/dashboard')
        _wait_until(page, present, 'the visible poll on load to record presence')

        page.evaluate("""() => {
            window.__visibility = 'hidden';
            Object.defineProperty(document, 'visibilityState', {configurable: true, get: () => window.__visibility});
            document.dispatchEvent(new Event('visibilitychange'));
            window.dispatchEvent(new PageTransitionEvent('pagehide'));   // hidden then closed: still one signal
        }""")
        _wait_until(page, lambda: not present(), 'the away signal to clear presence')
        page.wait_for_timeout(300)
        assert len(away_requests) == 1

        page.evaluate("() => { window.__visibility = 'visible'; document.dispatchEvent(new Event('visibilitychange')); }")
        _wait_until(page, present, 'the poll on becoming visible to record presence again')

        page.evaluate("() => { window.__visibility = 'hidden'; document.dispatchEvent(new Event('visibilitychange')); }")
        _wait_until(page, lambda: not present(), 'the second away signal')
        assert len(away_requests) == 2


class TestServiceWorker:

    def test_push_shows_a_notification_from_the_payload(self, app, live_server, browser_context):
        browser_context.grant_permissions(['notifications'], origin=live_server)
        page = browser_context.new_page()
        page.goto(live_server + '/login')
        page.evaluate('navigator.serviceWorker.ready.then(() => true)')
        worker = browser_context.service_workers[0] if browser_context.service_workers \
            else browser_context.wait_for_event('serviceworker')

        shown = worker.evaluate("""async () => {
            const push = (data) => {
                const init = data === undefined ? {} : {data};
                try { self.dispatchEvent(new PushEvent('push', init)); } catch (e) {}
            };
            push(JSON.stringify({title: 'Stop Loss triggered', body: 'Sold 3 Coal', tag: 'sl-1', url: '/history'}));
            push(undefined);          // no payload still shows a notification
            push('not json');         // nor does a broken one stop it
            await new Promise((r) => setTimeout(r, 500));
            const list = await self.registration.getNotifications();
            list.forEach((n) => n.close());
            return list.map((n) => ({title: n.title, body: n.body, tag: n.tag, url: n.data && n.data.url}));
        }""")
        assert {'title': 'Stop Loss triggered', 'body': 'Sold 3 Coal', 'tag': 'sl-1', 'url': '/history'} in shown
        fallbacks = [n for n in shown if n['title'] == 'OreX']
        assert len(fallbacks) == 2 and all(n['url'] == '/inbox' and n['body'] == '' for n in fallbacks)
