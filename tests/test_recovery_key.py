"""Tests for the inline recovery-key "forgot password" feature and the admin reset script.

The key is shown inside the register and set-new-password forms and carried in a
signed, time-limited token; nothing is stored until the form is submitted.
"""

import contextlib
import os
import re
import sqlite3
import sys
import time
from unittest.mock import patch

import pyotp
import pytest
from hypothesis import HealthCheck, given, settings, strategies as st

from conftest import get_csrf_token, register_user, login_user
from app.models import enable_2fa
from app.recovery_form import issue_token
from app.totp import (
    RECOVERY_KEY_ALPHABET,
    encrypt_secret,
    generate_recovery_key,
    generate_secret,
    normalize_recovery_key,
    verify_recovery_key,
    hash_recovery_key,
)

PASSWORD = 'Password123!'
NEW_PASSWORD = 'NewPassword456!'
GENERIC = 'Invalid username or recovery key.'
EXPIRED = 'Your recovery key expired, so a new one was generated; please save it.'
CONFIRM = 'Please confirm that you have saved your recovery key.'
KEY_RE = re.compile(r'id="recovery-key-value">([A-Z2-9-]+)<')
TOKEN_RE = re.compile(r'name="recovery_token" value="([^"]+)"')
KEY_SHAPE = r'([A-Z2-9]{4}-){4}[A-Z2-9]{4}'


@pytest.fixture(autouse=True)
def clean_session(client):
    """The test client is session-scoped; drop cookies/session between tests."""
    client.delete_cookie('remember_token')
    with client.session_transaction() as sess:
        sess.clear()
    yield
    client.delete_cookie('remember_token')
    with client.session_transaction() as sess:
        sess.clear()


@contextlib.contextmanager
def _db(app):
    conn = sqlite3.connect(app.config['DATABASE_PATH'])
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def _page_parts(resp):
    """(csrf, key, token) shown on a register / reset page."""
    html = resp.data.decode()
    key = KEY_RE.search(html)
    token = TOKEN_RE.search(html)
    assert key and token, 'recovery key block not found on page'
    return get_csrf_token(resp), key.group(1), token.group(1)


def _register_page(client):
    resp = client.get('/register')
    assert resp.status_code == 200
    return _page_parts(resp)


def _register(client, username='RkUser', ticked=True, saved=True, parts=None, token=None, **extra):
    """POST /register. Returns (response, key, token) for the block that was submitted."""
    csrf, key, tok = parts or _register_page(client)
    data = {
        'username': username,
        'password': PASSWORD,
        'confirm_password': PASSWORD,
        'csrf_token': csrf,
        'recovery_token': tok if token is None else token,
    }
    if ticked:
        data['generate_recovery_key'] = '1'
    if saved:
        data['recovery_saved'] = '1'
    data.update(extra)
    return client.post('/register', data=data, follow_redirects=False), key, tok


def _user_with_key(client, username='RkUser'):
    """Register with a key (saved), log out. Returns the plain key."""
    resp, key, _ = _register(client, username)
    assert '/dashboard' in resp.headers['Location']
    client.get('/logout')
    return key


def _forgot(client, username, key):
    token = get_csrf_token(client.get('/forgot-password'))
    return client.post('/forgot-password', data={
        'username': username, 'recovery_key': key, 'csrf_token': token,
    }, follow_redirects=False)


def _reset_page(client):
    resp = client.get('/reset-password')
    assert resp.status_code == 200
    return _page_parts(resp)


def _reset(client, password=NEW_PASSWORD, confirm=None, ticked=True, saved=True,
           parts=None, token=None):
    """POST /reset-password. Returns (response, key, token) for the block submitted."""
    csrf, key, tok = parts or _reset_page(client)
    data = {
        'password': password,
        'confirm_password': password if confirm is None else confirm,
        'csrf_token': csrf,
        'recovery_token': tok if token is None else token,
    }
    if ticked:
        data['generate_recovery_key'] = '1'
    if saved:
        data['recovery_saved'] = '1'
    return client.post('/reset-password', data=data, follow_redirects=False), key, tok


def _aged_token(app, key, purpose, user_id=None, age=0):
    """A valid token that was issued ``age`` seconds ago."""
    with app.app_context(), patch('time.time', return_value=time.time() - age):
        return issue_token(key, purpose, user_id)


def _user_id(app):
    with _db(app) as conn:
        return conn.execute('SELECT id FROM users').fetchone()['id']


def _key_hashes(app):
    with _db(app) as conn:
        return [r['key_hash'] for r in conn.execute('SELECT key_hash FROM recovery_keys')]


def _user_count(app):
    with _db(app) as conn:
        return conn.execute('SELECT COUNT(*) FROM users').fetchone()[0]


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

class TestRegistration:
    def test_checkbox_present_unticked_and_block_markup(self, client):
        resp = client.get('/register')
        html = resp.data.decode()
        assert 'name="generate_recovery_key"' in html
        assert not re.search(r'name="generate_recovery_key"[^>]*checked', html)
        assert 'Lets you reset your password if you forget it.' in html
        assert 'Save this key now.' in html
        assert 'It works once and will not be shown again.' in html
        assert re.search(KEY_SHAPE, KEY_RE.search(html).group(1))
        assert 'id="recovery-key-copy"' in html and 'aria-label="Copy recovery key"' in html
        assert 'id="recovery-key-status"' in html and 'aria-live="polite"' in html
        assert 'name="recovery_saved"' in html and 'required-mark' in html
        # Disabled-state hooks: hint element linked from the button, script on load.
        assert 'id="recovery-hint"' in html
        assert re.search(r'id="recovery-submit"\s+aria-describedby="recovery-hint"', html)
        assert 'Tick "I have saved my recovery key" to continue.' in html
        assert 'Create Account</button>' in html
        # No key page endpoints are referenced.
        assert '/recovery-key' not in html

    def test_page_with_key_is_no_store(self, client):
        assert client.get('/register').headers['Cache-Control'] == 'no-store'

    def test_each_render_has_a_new_key(self, client):
        assert _register_page(client)[1] != _register_page(client)[1]

    def test_without_checkbox_creates_no_key(self, client, app):
        resp, _key, _ = _register(client, ticked=False, saved=False)
        assert '/dashboard' in resp.headers['Location']
        assert _key_hashes(app) == []

    def test_without_checkbox_ignores_token_and_confirmation(self, client, app):
        resp, _key, _ = _register(client, ticked=False, saved=True)
        assert '/dashboard' in resp.headers['Location']
        assert _key_hashes(app) == []

    def test_without_checkbox_ignores_bad_token(self, client, app):
        resp, _key, _ = _register(client, ticked=False, token='garbage')
        assert '/dashboard' in resp.headers['Location']
        assert _key_hashes(app) == []

    def test_with_key_creates_account_and_hash_in_one_submit(self, client, app):
        resp, key, _ = _register(client)
        assert resp.status_code == 302
        assert '/dashboard' in resp.headers['Location']  # no key page in between
        assert client.get('/dashboard').status_code == 200  # logged in
        hashes = _key_hashes(app)
        assert len(hashes) == 1
        assert verify_recovery_key(hashes[0], key)
        assert key not in hashes[0]
        assert normalize_recovery_key(key) not in hashes[0]

    def test_ticked_without_confirmation_rejected_server_side(self, client, app):
        resp, key, _ = _register(client, saved=False)
        assert resp.status_code == 200
        html = resp.data.decode()
        assert CONFIRM in html
        assert _user_count(app) == 0 and _key_hashes(app) == []
        # Same key re-rendered, confirmation checkbox unticked again.
        assert _page_parts(resp)[1] == key
        assert not re.search(r'name="recovery_saved"[^>]*checked', html)
        assert client.get('/dashboard').status_code == 302  # not logged in

    def test_missing_token_rejected(self, client, app):
        csrf, _key, _tok = _register_page(client)
        resp = client.post('/register', data={
            'username': 'RkUser', 'password': PASSWORD, 'confirm_password': PASSWORD,
            'csrf_token': csrf, 'generate_recovery_key': '1', 'recovery_saved': '1',
        })
        assert resp.status_code == 200 and EXPIRED in resp.data.decode()
        assert _user_count(app) == 0 and _key_hashes(app) == []

    def test_tampered_token_rejected_with_new_key(self, client, app):
        resp, key, tok = _register(client)  # a valid first submit would succeed; use a new user page
        client.get('/logout')
        parts = _register_page(client)
        bad = parts[2][:-3] + ('AAA' if not parts[2].endswith('AAA') else 'BBB')
        resp, key, _ = _register(client, 'Other', parts=parts, token=bad)
        assert resp.status_code == 200
        html = resp.data.decode()
        assert EXPIRED in html
        assert _page_parts(resp)[1] != key
        assert _user_count(app) == 1  # only the first user exists
        assert len(_key_hashes(app)) == 1

    def test_forged_key_in_form_field_is_not_accepted(self, client, app):
        resp, key, _ = _register(client, token='x.y.z', recovery_key=generate_recovery_key())
        assert resp.status_code == 200 and EXPIRED in resp.data.decode()
        assert _key_hashes(app) == []

    def test_expired_token_rejected(self, client, app):
        key = generate_recovery_key()
        old = _aged_token(app, key, 'register', age=31 * 60)
        resp, _k, _ = _register(client, token=old)
        html = resp.data.decode()
        assert resp.status_code == 200 and EXPIRED in html
        assert _page_parts(resp)[1] != key
        assert _user_count(app) == 0 and _key_hashes(app) == []

    def test_token_valid_just_before_expiry(self, client, app):
        key = generate_recovery_key()
        tok = _aged_token(app, key, 'register', age=29 * 60)
        resp, _k, _ = _register(client, token=tok)
        assert '/dashboard' in resp.headers['Location']
        assert verify_recovery_key(_key_hashes(app)[0], key)

    def test_wrong_purpose_token_rejected(self, client, app):
        tok = _aged_token(app, generate_recovery_key(), 'reset', user_id=1)
        resp, _k, _ = _register(client, token=tok)
        assert resp.status_code == 200 and EXPIRED in resp.data.decode()
        assert _user_count(app) == 0

    def test_failed_submit_taken_username_rerenders_same_key(self, client, app):
        register_user(client, 'Taken', PASSWORD)
        client.get('/logout')
        resp, key, _ = _register(client, 'Taken')
        html = resp.data.decode()
        assert resp.status_code == 200 and 'already taken' in html
        assert _page_parts(resp)[1] == key
        assert re.search(r'name="generate_recovery_key"[^>]*checked', html)
        assert resp.headers['Cache-Control'] == 'no-store'
        assert _key_hashes(app) == []
        # The re-rendered token works for the retry: the saved copy stays valid.
        parts = _page_parts(resp)
        resp2, _k, _ = _register(client, 'Fresh', parts=parts)
        assert '/dashboard' in resp2.headers['Location']
        assert verify_recovery_key(_key_hashes(app)[0], key)

    def test_failed_submit_bad_password_rerenders_same_key(self, client, app):
        csrf, key, tok = _register_page(client)
        resp = client.post('/register', data={
            'username': 'RkUser', 'password': 'short', 'confirm_password': 'short',
            'csrf_token': csrf, 'generate_recovery_key': '1', 'recovery_saved': '1',
            'recovery_token': tok,
        })
        html = resp.data.decode()
        assert resp.status_code == 200 and 'Password must' in html
        assert _page_parts(resp)[1] == key
        assert not re.search(r'name="recovery_saved"[^>]*checked', html)
        assert _user_count(app) == 0

    def test_failed_submit_mismatch_unticked_keeps_key_and_state(self, client):
        csrf, key, tok = _register_page(client)
        resp = client.post('/register', data={
            'username': 'RkUser', 'password': PASSWORD, 'confirm_password': 'Different789!',
            'csrf_token': csrf, 'recovery_token': tok,
        })
        html = resp.data.decode()
        assert 'Passwords do not match.' in html
        assert not re.search(r'name="generate_recovery_key"[^>]*checked', html)
        assert _page_parts(resp)[1] == key

    def test_key_never_in_session_or_database_in_plain_form(self, client, app):
        _resp, key, _ = _register(client)
        plain = {key, normalize_recovery_key(key)}
        with client.session_transaction() as sess:
            for k, v in dict(sess).items():
                assert not any(p in f'{k}{v}' for p in plain)
        with open(app.config['DATABASE_PATH'], 'rb') as fh:
            raw = fh.read()
        for p in plain:
            assert p.encode() not in raw

    def test_key_not_logged(self, client, caplog):
        with caplog.at_level('DEBUG'):
            _resp, key, _ = _register(client)
        assert key not in caplog.text and normalize_recovery_key(key) not in caplog.text

    def test_nothing_stored_before_submit(self, client, app):
        _register_page(client)
        _register_page(client)
        assert _user_count(app) == 0 and _key_hashes(app) == []

    def test_key_page_routes_are_gone(self, client):
        for method, path in [
            ('get', '/recovery-key'),
            ('post', '/recovery-key/continue'),
            ('post', '/recovery-key/regenerate'),
            ('post', '/recovery-key/skip'),
        ]:
            assert getattr(client, method)(path).status_code in (404, 405), path
        assert client.get('/recovery-key').status_code == 404
        assert client.post('/recovery-key/continue', data={}).status_code in (400, 404)

    def test_authenticated_user_redirected_from_register(self, authenticated_client):
        resp = authenticated_client.get('/register')
        assert resp.status_code == 302 and '/dashboard' in resp.headers['Location']

    def test_registration_atomic_if_key_insert_fails(self, client, app):
        import app.models as models
        real_get_db = models.get_db
        parts = _register_page(client)
        with patch.object(models, 'get_db', lambda: _FailingDb(real_get_db(), 'INSERT INTO recovery_keys')), \
                patch.dict(app.config, {'PROPAGATE_EXCEPTIONS': True}):
            with pytest.raises(sqlite3.OperationalError):
                _register(client, parts=parts)
        assert _user_count(app) == 0 and _key_hashes(app) == []

    def test_delete_account_removes_key_row(self, client, app):
        _register(client)
        uid = _user_id(app)
        assert len(_key_hashes(app)) == 1
        from app.models import delete_account
        with app.app_context():
            delete_account(uid)
        assert _key_hashes(app) == []

    def test_init_db_idempotent_with_existing_table(self, client, app):
        _register(client)
        with _db(app) as conn:
            before = conn.execute('SELECT user_id, key_hash FROM recovery_keys').fetchall()
        from types import SimpleNamespace
        from app.database import init_db
        # Stand-in app: the real one has already served requests and refuses new teardown hooks.
        stub = SimpleNamespace(config=app.config, teardown_appcontext=lambda f: None)
        init_db(stub)
        init_db(stub)
        with _db(app) as conn:
            after = conn.execute('SELECT user_id, key_hash FROM recovery_keys').fetchall()
        assert [tuple(r) for r in before] == [tuple(r) for r in after] and before

    def test_csrf_required(self, client):
        assert client.post('/register', data={'username': 'x'}).status_code == 400


# ---------------------------------------------------------------------------
# Forgot / reset flow
# ---------------------------------------------------------------------------

class TestForgotPasswordFlow:
    def test_login_page_links_to_forgot(self, client):
        assert 'href="/forgot-password"' in client.get('/login').data.decode()

    def test_reset_page_markup_default_ticked(self, client):
        key = _user_with_key(client)
        _forgot(client, 'RkUser', key)
        resp = client.get('/reset-password')
        html = resp.data.decode()
        assert resp.headers['Cache-Control'] == 'no-store'
        assert 'Set a New Password' in html
        assert 'Choose a new password for your account. This page expires in 5 minutes.' in html
        assert 'New password' in html and 'Confirm new password' in html
        assert re.search(r'name="generate_recovery_key"[^>]*checked', html)
        assert 'Reset Password</button>' in html
        assert 'id="recovery-hint"' in html and 'aria-describedby="recovery-hint"' in html

    def test_full_success_flow_with_new_key(self, client, app):
        old_key = _user_with_key(client)
        resp = _forgot(client, 'RkUser', old_key)
        assert resp.status_code == 302 and '/reset-password' in resp.headers['Location']

        resp, new_key, _ = _reset(client)
        assert resp.status_code == 302 and '/login' in resp.headers['Location']  # no key page
        assert new_key != old_key
        assert 'Your password has been reset' in client.get('/login').data.decode()

        # Not auto-logged-in; new password works, old does not.
        assert client.get('/dashboard').status_code == 302
        assert login_user(client, 'RkUser', PASSWORD).status_code == 200
        assert '/dashboard' in login_user(client, 'RkUser', NEW_PASSWORD).headers['Location']
        client.get('/logout')

        # Old key consumed, new key works.
        assert GENERIC in _forgot(client, 'RkUser', old_key).data.decode()
        assert '/reset-password' in _forgot(client, 'RkUser', new_key).headers['Location']

    def test_success_without_new_key(self, client, app):
        old_key = _user_with_key(client)
        _forgot(client, 'RkUser', old_key)
        resp, _k, _ = _reset(client, ticked=False, saved=False)
        assert resp.status_code == 302 and '/login' in resp.headers['Location']
        assert _key_hashes(app) == []  # old consumed, nothing new stored
        assert '/dashboard' in login_user(client, 'RkUser', NEW_PASSWORD).headers['Location']
        client.get('/logout')
        assert GENERIC in _forgot(client, 'RkUser', old_key).data.decode()

    def test_no_inbox_notification_created(self, client, app):
        key = _user_with_key(client)
        _forgot(client, 'RkUser', key)
        _reset(client)
        with _db(app) as conn:
            assert conn.execute('SELECT COUNT(*) FROM notifications').fetchone()[0] == 0

    def test_ticked_without_confirmation_rejected_nothing_changes(self, client, app):
        key = _user_with_key(client)
        _forgot(client, 'RkUser', key)
        before = _snapshot(app)
        resp, shown, _ = _reset(client, saved=False)
        assert resp.status_code == 200 and CONFIRM in resp.data.decode()
        assert _snapshot(app) == before
        assert _page_parts(resp)[1] == shown
        assert not re.search(r'name="recovery_saved"[^>]*checked', resp.data.decode())
        # Pending session survives: the retry with the same re-rendered key succeeds.
        resp2, _k, _ = _reset(client, parts=_page_parts(resp))
        assert '/login' in resp2.headers['Location']
        assert verify_recovery_key(_key_hashes(app)[0], shown)

    def test_validation_errors_keep_session_and_same_key(self, client, app):
        key = _user_with_key(client)
        _forgot(client, 'RkUser', key)
        csrf, shown, tok = _reset_page(client)

        weak, _k, _ = _reset(client, 'weak', parts=(csrf, shown, tok))
        assert weak.status_code == 200 and 'Password must' in weak.data.decode()
        assert _page_parts(weak)[1] == shown
        assert weak.headers['Cache-Control'] == 'no-store'
        assert not re.search(r'name="recovery_saved"[^>]*checked', weak.data.decode())

        mismatch, _k, _ = _reset(client, NEW_PASSWORD, confirm='Different789!',
                                 parts=_page_parts(weak))
        assert mismatch.status_code == 200 and 'Passwords do not match.' in mismatch.data.decode()
        assert _page_parts(mismatch)[1] == shown

        # Session survives the errors; the key the user copied is the one stored.
        done, _k, _ = _reset(client, parts=_page_parts(mismatch))
        assert '/login' in done.headers['Location']
        assert verify_recovery_key(_key_hashes(app)[0], shown)

    def test_missing_tampered_expired_tokens_rejected(self, client, app):
        key = _user_with_key(client)
        _forgot(client, 'RkUser', key)
        uid = _user_id(app)
        before = _snapshot(app)
        good = generate_recovery_key()
        cases = {
            'missing': '',
            'tampered': _aged_token(app, good, 'reset', uid)[:-3] + 'AAA',
            'expired': _aged_token(app, good, 'reset', uid, age=301),
        }
        for label, tok in cases.items():
            resp, _k, _ = _reset(client, token=tok)
            assert resp.status_code == 200, label
            assert EXPIRED in resp.data.decode(), label
            assert _page_parts(resp)[1] != good, label
            assert _snapshot(app) == before, label
        # Still pending: a fresh page works.
        assert '/login' in _reset(client)[0].headers['Location']

    def test_registration_token_refused_on_reset_page(self, client, app):
        _csrf, _key, reg_token = _register_page(client)
        key = _user_with_key(client)
        _forgot(client, 'RkUser', key)
        before = _snapshot(app)
        resp, _k, _ = _reset(client, token=reg_token)
        assert resp.status_code == 200 and EXPIRED in resp.data.decode()
        assert _snapshot(app) == before

    def test_reset_token_refused_on_register_page(self, client, app):
        key = _user_with_key(client)
        _forgot(client, 'RkUser', key)
        _csrf, _k, reset_token = _reset_page(client)
        client.get('/logout')
        with client.session_transaction() as sess:
            sess.clear()
        resp, _k2, _ = _register(client, 'Another', token=reset_token)
        assert resp.status_code == 200 and EXPIRED in resp.data.decode()
        assert _user_count(app) == 1

    def test_token_for_another_user_refused_on_reset(self, client, app):
        key = _user_with_key(client)
        _forgot(client, 'RkUser', key)
        uid = _user_id(app)
        other = _aged_token(app, generate_recovery_key(), 'reset', uid + 1)
        resp, _k, _ = _reset(client, token=other)
        assert resp.status_code == 200 and EXPIRED in resp.data.decode()

    def test_key_format_variants_accepted(self, client):
        key = _user_with_key(client)
        sloppy = key.lower().replace('-', ' ')
        assert '/reset-password' in _forgot(client, 'RkUser', f'  {sloppy} ').headers['Location']

    def test_identical_failures(self, client):
        key = _user_with_key(client, 'HasKey')
        register_user(client, 'NoKey', PASSWORD)
        client.get('/logout')
        other = generate_recovery_key()

        responses = [
            _forgot(client, 'Nobody', other),        # unknown user
            _forgot(client, 'NoKey', other),         # user without key
            _forgot(client, 'HasKey', other),        # wrong key
        ]
        for r in responses:
            assert r.status_code == 200
            assert GENERIC in r.data.decode()
        # Failed attempts do not create a reset session.
        assert client.get('/reset-password').status_code == 302
        assert key  # silence unused warning

    def test_dummy_hash_check_for_unknown_user_and_no_key(self, client):
        register_user(client, 'NoKey', PASSWORD)
        client.get('/logout')
        with patch('app.totp.check_password_hash', return_value=False) as mocked:
            _forgot(client, 'Nobody', generate_recovery_key())
            assert mocked.call_count == 1
            _forgot(client, 'NoKey', generate_recovery_key())
            assert mocked.call_count == 2

    def test_rate_limited_after_five_failures(self, client):
        for _ in range(5):
            assert GENERIC in _forgot(client, 'Nobody', generate_recovery_key()).data.decode()
        resp = _forgot(client, 'Nobody', generate_recovery_key())
        assert 'Too many attempts' in resp.data.decode()

    def test_rate_limit_shared_with_login(self, client):
        for _ in range(3):
            login_user(client, 'Nobody', 'wrong')
        for _ in range(2):
            _forgot(client, 'Nobody', generate_recovery_key())
        assert 'Too many attempts' in _forgot(client, 'Nobody', generate_recovery_key()).data.decode()
        assert 'Too many login attempts' in login_user(client, 'Nobody', 'x').data.decode()

    def test_reset_page_requires_verified_session(self, client):
        resp = client.get('/reset-password')
        assert resp.status_code == 302 and '/forgot-password' in resp.headers['Location']
        token = get_csrf_token(client.get('/forgot-password'))
        resp = client.post('/reset-password', data={
            'password': NEW_PASSWORD, 'confirm_password': NEW_PASSWORD, 'csrf_token': token,
        })
        assert resp.status_code == 302 and '/forgot-password' in resp.headers['Location']

    def test_pending_reset_session_expires(self, client, app):
        key = _user_with_key(client)
        _forgot(client, 'RkUser', key)
        with client.session_transaction() as sess:
            sess['pending_reset_time'] = time.time() - 301
        resp = client.get('/reset-password')
        assert resp.status_code == 302 and '/forgot-password' in resp.headers['Location']
        # Password unchanged.
        assert '/dashboard' in login_user(client, 'RkUser', PASSWORD).headers['Location']

    def test_pending_reset_session_expiry_blocks_post(self, client, app):
        key = _user_with_key(client)
        _forgot(client, 'RkUser', key)
        parts = _reset_page(client)
        with client.session_transaction() as sess:
            sess['pending_reset_time'] = time.time() - 301
        resp, _k, _ = _reset(client, parts=parts)
        assert resp.status_code == 302 and '/forgot-password' in resp.headers['Location']
        assert verify_recovery_key(_key_hashes(app)[0], key)  # old key untouched

    def test_pending_reset_session_valid_before_expiry(self, client):
        key = _user_with_key(client)
        _forgot(client, 'RkUser', key)
        with client.session_transaction() as sess:
            sess['pending_reset_time'] = time.time() - 290
        assert client.get('/reset-password').status_code == 200

    def test_authenticated_users_redirected(self, authenticated_client):
        for path in ('/forgot-password', '/reset-password'):
            resp = authenticated_client.get(path)
            assert resp.status_code == 302 and '/dashboard' in resp.headers['Location']
        resp = authenticated_client.post('/forgot-password', data={})
        assert resp.status_code in (302, 400)

    def test_csrf_required(self, client):
        assert client.post('/forgot-password', data={
            'username': 'a', 'recovery_key': 'b'}).status_code == 400
        key = _user_with_key(client)
        _forgot(client, 'RkUser', key)
        assert client.post('/reset-password', data={
            'password': NEW_PASSWORD, 'confirm_password': NEW_PASSWORD}).status_code == 400

    def test_2fa_stays_enabled_and_required(self, client, app):
        key = _user_with_key(client)
        uid = _user_id(app)
        secret = generate_secret()
        with app.app_context():
            enable_2fa(uid, encrypt_secret(secret, app.config['SECRET_KEY']))

        _forgot(client, 'RkUser', key)
        _reset(client)

        with _db(app) as conn:
            row = conn.execute(
                'SELECT totp_enabled, totp_secret_encrypted FROM users').fetchone()
        assert row['totp_enabled'] == 1 and row['totp_secret_encrypted']

        resp = login_user(client, 'RkUser', NEW_PASSWORD)
        assert '/login/2fa' in resp.headers['Location']
        assert pyotp.TOTP(secret).now()  # secret still usable

    def test_reset_fails_if_key_already_consumed(self, client, app):
        key = _user_with_key(client)
        _forgot(client, 'RkUser', key)
        with _db(app) as conn:
            conn.execute('DELETE FROM recovery_keys')
            conn.commit()
        resp, _k, _ = _reset(client)
        assert resp.status_code == 302 and '/forgot-password' in resp.headers['Location']
        assert '/dashboard' in login_user(client, 'RkUser', PASSWORD).headers['Location']

    def test_end_to_end_walkthrough(self, client, app):
        """register with key -> logout -> forgot -> set new password + new key ->
        login -> forgot again with the NEW key works, the old one does not."""
        resp, key1, _ = _register(client, 'Walker')
        assert '/dashboard' in resp.headers['Location']
        client.get('/logout')

        assert '/reset-password' in _forgot(client, 'Walker', key1).headers['Location']
        resp, key2, _ = _reset(client)
        assert '/login' in resp.headers['Location'] and key2 != key1

        assert '/dashboard' in login_user(client, 'Walker', NEW_PASSWORD).headers['Location']
        client.get('/logout')

        assert GENERIC in _forgot(client, 'Walker', key1).data.decode()
        assert '/reset-password' in _forgot(client, 'Walker', key2).headers['Location']


# ---------------------------------------------------------------------------
# Atomic reset
# ---------------------------------------------------------------------------

class _FailingDb:
    """Delegates to the real connection but raises on a statement containing `needle`."""

    def __init__(self, real, needle):
        self._real = real
        self._needle = needle

    def execute(self, sql, *args, **kwargs):
        if self._needle in sql:
            raise sqlite3.OperationalError('simulated failure')
        return self._real.execute(sql, *args, **kwargs)

    def commit(self):
        return self._real.commit()

    def rollback(self):
        return self._real.rollback()


def _snapshot(app):
    with _db(app) as conn:
        key_row = conn.execute('SELECT user_id, key_hash FROM recovery_keys').fetchone()
        return (
            conn.execute('SELECT password_hash FROM users').fetchone()[0],
            tuple(key_row) if key_row else None,
        )


class TestAtomicReset:
    def test_success_commits_all_effects(self, client, app):
        key = _user_with_key(client)
        before = _snapshot(app)
        _forgot(client, 'RkUser', key)
        resp, new_key, _ = _reset(client)
        assert '/login' in resp.headers['Location']
        pw, key_row = _snapshot(app)
        assert pw != before[0]                                  # password changed
        assert key_row[1] != before[1][1]                       # new key hash stored
        assert not verify_recovery_key(key_row[1], key)         # old key gone
        assert verify_recovery_key(key_row[1], new_key)

    @pytest.mark.parametrize('needle', [
        'DELETE FROM recovery_keys',
        'UPDATE users SET password_hash',
        'INSERT INTO recovery_keys',
    ])
    def test_failure_at_each_step_rolls_back_everything(self, client, app, needle):
        import app.models as models
        key = _user_with_key(client)
        _forgot(client, 'RkUser', key)
        parts = _reset_page(client)
        before = _snapshot(app)

        real_get_db = models.get_db
        with patch.object(models, 'get_db', lambda: _FailingDb(real_get_db(), needle)), \
                patch.dict(app.config, {'PROPAGATE_EXCEPTIONS': True}):
            with pytest.raises(sqlite3.OperationalError):
                _reset(client, parts=parts)

        assert _snapshot(app) == before
        # Old password and old key still work.
        assert '/dashboard' in login_user(client, 'RkUser', PASSWORD).headers['Location']
        client.get('/logout')
        assert '/reset-password' in _forgot(client, 'RkUser', key).headers['Location']

    def test_double_submit_second_fails_first_intact(self, client, app):
        key = _user_with_key(client)
        other = app.test_client()
        _forgot(client, 'RkUser', key)
        _forgot(other, 'RkUser', key)
        parts_a = _reset_page(client)
        parts_b = _reset_page(other)

        first, _k, _ = _reset(client, parts=parts_a)
        assert '/login' in first.headers['Location']
        after_first = _snapshot(app)

        second, _k, _ = _reset(other, 'OtherPassword789!', parts=parts_b)
        assert second.status_code == 302 and '/forgot-password' in second.headers['Location']
        assert _snapshot(app) == after_first
        assert verify_recovery_key(_key_hashes(app)[0], parts_a[1])

        assert login_user(client, 'RkUser', 'OtherPassword789!').status_code == 200
        assert '/dashboard' in login_user(client, 'RkUser', NEW_PASSWORD).headers['Location']


# ---------------------------------------------------------------------------
# Key helpers
# ---------------------------------------------------------------------------

class TestKeyHelpers:
    def test_generated_key_format(self):
        key = generate_recovery_key()
        groups = key.split('-')
        assert len(groups) == 5 and all(len(g) == 4 for g in groups)
        assert set(key.replace('-', '')) <= set(RECOVERY_KEY_ALPHABET)

    def test_keys_are_unique(self):
        assert len({generate_recovery_key() for _ in range(50)}) == 50

    @settings(max_examples=50, deadline=None,
              suppress_health_check=[HealthCheck.function_scoped_fixture])
    @given(
        raw=st.text(alphabet=RECOVERY_KEY_ALPHABET, min_size=20, max_size=20),
        seps=st.lists(st.sampled_from(['-', ' ', '  ', '\t', '--']), min_size=21, max_size=21),
        lower=st.booleans(),
    )
    def test_normalization_ignores_dashes_spaces_case(self, raw, seps, lower):
        decorated = seps[0] + ''.join(c + s for c, s in zip(raw, seps[1:]))
        if lower:
            decorated = decorated.lower()
        assert normalize_recovery_key(decorated) == raw

    def test_verify_roundtrip(self):
        key = generate_recovery_key()
        stored = hash_recovery_key(key)
        assert verify_recovery_key(stored, key.lower().replace('-', ' '))
        assert not verify_recovery_key(stored, generate_recovery_key())


# ---------------------------------------------------------------------------
# Admin script
# ---------------------------------------------------------------------------

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'scripts', 'admin'))


class TestResetPasswordScript:
    def test_sets_password(self, client, app):
        import reset_password as script
        register_user(client, 'ScriptUser', PASSWORD)
        client.get('/logout')
        script.reset_password('ScriptUser', NEW_PASSWORD, app=app)
        assert login_user(client, 'ScriptUser', PASSWORD).status_code == 200
        assert '/dashboard' in login_user(client, 'ScriptUser', NEW_PASSWORD).headers['Location']

    def test_unknown_user_rejected(self, app):
        import reset_password as script
        with pytest.raises(SystemExit) as exc:
            script.reset_password('Ghost', NEW_PASSWORD, app=app)
        assert exc.value.code == 1

    def test_leaves_2fa_and_recovery_key_untouched(self, client, app):
        import reset_password as script
        _user_with_key(client, 'ScriptUser')
        with _db(app) as conn:
            user_id = conn.execute('SELECT id FROM users').fetchone()['id']
        with app.app_context():
            enable_2fa(user_id, encrypt_secret(generate_secret(), app.config['SECRET_KEY']))
        with _db(app) as conn:
            before = tuple(conn.execute(
                'SELECT totp_enabled, totp_secret_encrypted FROM users').fetchone())
            key_before = conn.execute('SELECT key_hash FROM recovery_keys').fetchone()[0]

        script.reset_password('ScriptUser', NEW_PASSWORD, app=app)

        with _db(app) as conn:
            after = tuple(conn.execute(
                'SELECT totp_enabled, totp_secret_encrypted FROM users').fetchone())
            key_after = conn.execute('SELECT key_hash FROM recovery_keys').fetchone()[0]
        assert before == after
        assert key_before == key_after

    def test_random_password_is_valid(self):
        import reset_password as script
        from app.utils.validation import validate_password
        for _ in range(20):
            assert validate_password(script.generate_temp_password())[0]

    def test_main_random_prints_password(self, client, app, capsys):
        import reset_password as script
        register_user(client, 'ScriptUser', PASSWORD)
        client.get('/logout')
        with patch.object(script, 'create_app', return_value=app):
            script.main(['reset_password.py', 'ScriptUser', '--random'])
        out = capsys.readouterr().out
        temp = out.split('Temporary password: ')[1].strip()
        assert '/dashboard' in login_user(client, 'ScriptUser', temp).headers['Location']
