"""Tests for the recovery-key "forgot password" feature and the admin reset script."""

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
KEY_RE = re.compile(r'id="recovery-key-value">([A-Z2-9-]+)<')


@pytest.fixture(autouse=True)
def clean_session(client):
    """The test client is session-scoped; drop cookies/session between tests."""
    with client.session_transaction() as sess:
        sess.clear()
    yield
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


def _register(client, username='RkUser', ticked=True):
    token = get_csrf_token(client.get('/register'))
    data = {
        'username': username,
        'password': PASSWORD,
        'confirm_password': PASSWORD,
        'csrf_token': token,
    }
    if ticked:
        data['generate_recovery_key'] = '1'
    return client.post('/register', data=data, follow_redirects=False)


def _read_key_page(client):
    resp = client.get('/recovery-key')
    assert resp.status_code == 200
    match = KEY_RE.search(resp.data.decode())
    assert match, 'recovery key not found on page'
    return match.group(1), get_csrf_token(resp), resp


def _confirm_key(client, csrf):
    return client.post('/recovery-key/continue', data={
        'confirmed': '1', 'csrf_token': csrf,
    }, follow_redirects=False)


def _user_with_key(client, username='RkUser'):
    """Register with a key, confirm it, log out. Returns the plain key."""
    resp = _register(client, username)
    assert '/recovery-key' in resp.headers['Location']
    key, csrf, _ = _read_key_page(client)
    done = _confirm_key(client, csrf)
    assert '/dashboard' in done.headers['Location']
    client.get('/logout')
    return key


def _forgot(client, username, key):
    token = get_csrf_token(client.get('/forgot-password'))
    return client.post('/forgot-password', data={
        'username': username, 'recovery_key': key, 'csrf_token': token,
    }, follow_redirects=False)


def _reset(client, password, confirm=None):
    token = get_csrf_token(client.get('/reset-password'))
    return client.post('/reset-password', data={
        'password': password,
        'confirm_password': password if confirm is None else confirm,
        'csrf_token': token,
    }, follow_redirects=False)


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

class TestRegistration:
    def test_checkbox_present_and_unticked(self, client):
        html = client.get('/register').data.decode()
        assert 'name="generate_recovery_key"' in html
        assert not re.search(r'name="generate_recovery_key"[^>]*checked', html)

    def test_without_checkbox_no_key_and_straight_to_dashboard(self, client, app):
        resp = _register(client, ticked=False)
        assert '/dashboard' in resp.headers['Location']
        with _db(app) as conn:
            assert conn.execute('SELECT COUNT(*) FROM recovery_keys').fetchone()[0] == 0
        assert client.get('/recovery-key').status_code == 302

    def test_with_checkbox_shows_key_page_once(self, client, app):
        resp = _register(client)
        assert resp.status_code == 302
        assert '/recovery-key' in resp.headers['Location']
        key, _csrf, page = _read_key_page(client)
        assert re.fullmatch(r'([A-Z2-9]{4}-){4}[A-Z2-9]{4}', key)
        assert page.headers['Cache-Control'] == 'no-store'
        html = page.data.decode()
        assert 'id="recovery-key-copy"' in html
        assert 'id="confirmed"' in html and 'required' in html
        assert 'disabled' in html

    def test_hash_stored_never_plain(self, client, app):
        _register(client)
        key, _csrf, _ = _read_key_page(client)
        with _db(app) as conn:
            row = conn.execute('SELECT key_hash FROM recovery_keys').fetchone()
        assert row is not None
        assert key not in row['key_hash']
        assert normalize_recovery_key(key) not in row['key_hash']
        assert verify_recovery_key(row['key_hash'], key)

    def test_key_not_retrievable_twice(self, client, app):
        _register(client)
        first, _csrf, _ = _read_key_page(client)
        with _db(app) as conn:
            hash_before = conn.execute('SELECT key_hash FROM recovery_keys').fetchone()['key_hash']

        for _ in range(2):  # repeated reloads never change anything
            resp = client.get('/recovery-key')
            html = resp.data.decode()
            assert resp.status_code == 200
            assert 'was already shown' in html
            assert 'id="recovery-key-value"' not in html
            assert first not in html
            assert resp.headers['Cache-Control'] == 'no-store'
            with _db(app) as conn:
                row = conn.execute('SELECT key_hash FROM recovery_keys').fetchone()
            assert row['key_hash'] == hash_before
            assert verify_recovery_key(row['key_hash'], first)

    def test_plain_key_absent_from_session_after_render(self, client):
        _register(client)
        with client.session_transaction() as sess:
            assert sess.get('recovery_key_plain')
        _read_key_page(client)
        with client.session_transaction() as sess:
            assert 'recovery_key_plain' not in sess

    def test_regenerate_requires_csrf(self, client, app):
        _register(client)
        _read_key_page(client)
        with _db(app) as conn:
            before = conn.execute('SELECT key_hash FROM recovery_keys').fetchone()[0]
        assert client.post('/recovery-key/regenerate', data={}).status_code == 400
        assert client.post('/recovery-key/skip', data={}).status_code == 400
        with _db(app) as conn:
            assert conn.execute('SELECT key_hash FROM recovery_keys').fetchone()[0] == before

    def test_regenerate_replaces_key(self, client, app):
        old_key = None
        _register(client, 'RkUser')
        old_key, _csrf, _ = _read_key_page(client)
        csrf = get_csrf_token(client.get('/recovery-key'))  # already-shown state
        resp = client.post('/recovery-key/regenerate', data={'csrf_token': csrf})
        assert resp.status_code == 302 and '/recovery-key' in resp.headers['Location']
        # Nothing displayed yet for the POST itself; the next GET shows the key once.
        new_key, csrf, _ = _read_key_page(client)
        assert new_key != old_key
        assert 'was already shown' in client.get('/recovery-key').data.decode()
        assert '/dashboard' in _confirm_key(client, csrf).headers['Location']
        client.get('/logout')

        assert GENERIC in _forgot(client, 'RkUser', old_key).data.decode()
        assert '/reset-password' in _forgot(client, 'RkUser', new_key).headers['Location']

    def test_regenerated_key_needs_confirmation(self, client):
        _register(client)
        _read_key_page(client)
        csrf = get_csrf_token(client.get('/recovery-key'))
        client.post('/recovery-key/regenerate', data={'csrf_token': csrf})
        _key, csrf, _ = _read_key_page(client)
        resp = client.post('/recovery-key/continue', data={'csrf_token': csrf})
        assert '/recovery-key' in resp.headers['Location']
        # Still pending (not finished) and still no way to skip the unseen state.
        assert client.get('/recovery-key').status_code == 200

    def test_skip_keeps_stored_key_valid(self, client, app):
        _register(client)
        key, _csrf, _ = _read_key_page(client)
        csrf = get_csrf_token(client.get('/recovery-key'))
        with _db(app) as conn:
            before = conn.execute('SELECT key_hash FROM recovery_keys').fetchone()[0]
        resp = client.post('/recovery-key/skip', data={'csrf_token': csrf})
        assert resp.status_code == 302 and '/dashboard' in resp.headers['Location']
        with _db(app) as conn:
            assert conn.execute('SELECT key_hash FROM recovery_keys').fetchone()[0] == before
        assert client.get('/recovery-key').status_code == 302  # flow finished
        client.get('/logout')
        assert '/reset-password' in _forgot(client, 'RkUser', key).headers['Location']

    def test_skip_not_allowed_before_key_was_shown(self, client):
        _register(client)
        csrf = get_csrf_token(client.get('/settings'))  # any page with a token
        resp = client.post('/recovery-key/skip', data={'csrf_token': csrf})
        assert resp.status_code == 302 and '/recovery-key' in resp.headers['Location']
        # Key was not consumed by that attempt: still displayable.
        assert 'id="recovery-key-value"' in client.get('/recovery-key').data.decode()

    def test_flow_ttl_applies_to_already_shown(self, client):
        _register(client)
        _read_key_page(client)
        with client.session_transaction() as sess:
            sess['recovery_key_time'] = time.time() - 601
        assert '/dashboard' in client.get('/recovery-key').headers['Location']

    def test_overlay_not_rendered_on_key_endpoints(self, client):
        _register(client)
        shown = client.get('/recovery-key').data.decode()
        again = client.get('/recovery-key').data.decode()
        for html in (shown, again):
            assert 'tutorial-root' not in html
        # Sanity: a normal authenticated page does render the overlay.
        assert 'tutorial-root' in client.get('/dashboard').data.decode()

    def test_delete_account_removes_key_row(self, client, app):
        _register(client)
        _read_key_page(client)
        with _db(app) as conn:
            user_id = conn.execute('SELECT id FROM users').fetchone()['id']
            assert conn.execute('SELECT COUNT(*) FROM recovery_keys').fetchone()[0] == 1
        from app.models import delete_account
        with app.app_context():
            delete_account(user_id)
        with _db(app) as conn:
            assert conn.execute('SELECT COUNT(*) FROM recovery_keys').fetchone()[0] == 0

    def test_init_db_idempotent_with_existing_table(self, client, app):
        _register(client)
        _read_key_page(client)
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

    def test_continue_without_confirmation_rejected(self, client):
        _register(client)
        _key, csrf, _ = _read_key_page(client)
        resp = client.post('/recovery-key/continue', data={'csrf_token': csrf})
        assert resp.status_code == 302
        assert '/recovery-key' in resp.headers['Location']
        # Flow still pending; the page is now in the already-shown state
        # and the user can still skip or regenerate.
        page = client.get('/recovery-key')
        assert 'was already shown' in page.data.decode()
        done = client.post('/recovery-key/skip', data={'csrf_token': get_csrf_token(page)})
        assert '/dashboard' in done.headers['Location']

    def test_confirmation_required_for_display_continue_without_flow_change(self, client):
        _register(client)
        key, csrf, page = _read_key_page(client)
        assert 'name="confirmed"' in page.data.decode()
        resp = client.post('/recovery-key/continue', data={'confirmed': '', 'csrf_token': csrf})
        assert '/recovery-key' in resp.headers['Location']

    def test_after_confirmation_page_is_gone(self, client):
        _register(client)
        _key, csrf, _ = _read_key_page(client)
        _confirm_key(client, csrf)
        resp = client.get('/recovery-key')
        assert resp.status_code == 302
        assert '/dashboard' in resp.headers['Location']

    def test_key_page_requires_flow(self, client):
        resp = client.get('/recovery-key')
        assert resp.status_code == 302
        assert '/login' in resp.headers['Location']

    def test_continue_requires_csrf(self, client):
        _register(client)
        _read_key_page(client)
        resp = client.post('/recovery-key/continue', data={'confirmed': '1'})
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Forgot / reset flow
# ---------------------------------------------------------------------------

class TestForgotPasswordFlow:
    def test_login_page_links_to_forgot(self, client):
        assert 'href="/forgot-password"' in client.get('/login').data.decode()

    def test_full_success_flow(self, client, app):
        old_key = _user_with_key(client)
        resp = _forgot(client, 'RkUser', old_key)
        assert resp.status_code == 302 and '/reset-password' in resp.headers['Location']

        resp = _reset(client, NEW_PASSWORD)
        assert resp.status_code == 302 and '/recovery-key' in resp.headers['Location']

        # New key shown once, differs from the old one.
        new_key, csrf, _ = _read_key_page(client)
        assert new_key != old_key
        done = _confirm_key(client, csrf)
        assert '/login' in done.headers['Location']
        assert 'Your password has been reset' in client.get('/login').data.decode()

        # Not auto-logged-in; new password works, old does not.
        assert client.get('/dashboard').status_code == 302
        assert login_user(client, 'RkUser', PASSWORD).status_code == 200
        assert '/dashboard' in login_user(client, 'RkUser', NEW_PASSWORD).headers['Location']
        client.get('/logout')

        # Old key consumed, new key works.
        assert GENERIC in _forgot(client, 'RkUser', old_key).data.decode()
        assert '/reset-password' in _forgot(client, 'RkUser', new_key).headers['Location']

    def test_notification_created(self, client, app):
        key = _user_with_key(client)
        _forgot(client, 'RkUser', key)
        _reset(client, NEW_PASSWORD)
        with _db(app) as conn:
            rows = conn.execute('SELECT category, message FROM notifications').fetchall()
        assert [(r['category'], r['message']) for r in rows] == [
            ('security', 'Your password was reset using your recovery key.')
        ]

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

    def test_validation_errors_keep_session(self, client):
        key = _user_with_key(client)
        _forgot(client, 'RkUser', key)

        weak = _reset(client, 'weak')
        assert weak.status_code == 200 and 'Password must' in weak.data.decode()
        mismatch = _reset(client, NEW_PASSWORD, confirm='Different789!')
        assert mismatch.status_code == 200 and 'Passwords do not match.' in mismatch.data.decode()

        # Session survives the errors and the reset still succeeds.
        assert '/recovery-key' in _reset(client, NEW_PASSWORD).headers['Location']

    def test_csrf_required(self, client):
        assert client.post('/forgot-password', data={
            'username': 'a', 'recovery_key': 'b'}).status_code == 400
        key = _user_with_key(client)
        _forgot(client, 'RkUser', key)
        assert client.post('/reset-password', data={
            'password': NEW_PASSWORD, 'confirm_password': NEW_PASSWORD}).status_code == 400

    def test_2fa_stays_enabled_and_required(self, client, app):
        key = _user_with_key(client)
        with _db(app) as conn:
            user_id = conn.execute('SELECT id FROM users').fetchone()['id']
        secret = generate_secret()
        with app.app_context():
            enable_2fa(user_id, encrypt_secret(secret, app.config['SECRET_KEY']))

        _forgot(client, 'RkUser', key)
        _reset(client, NEW_PASSWORD)
        _k, csrf, _ = _read_key_page(client)
        _confirm_key(client, csrf)

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
        resp = _reset(client, NEW_PASSWORD)
        assert resp.status_code == 302 and '/forgot-password' in resp.headers['Location']
        assert '/dashboard' in login_user(client, 'RkUser', PASSWORD).headers['Location']


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
        return (
            conn.execute('SELECT password_hash FROM users').fetchone()[0],
            tuple(conn.execute('SELECT user_id, key_hash FROM recovery_keys').fetchone()),
            conn.execute('SELECT COUNT(*) FROM notifications').fetchone()[0],
        )


class TestAtomicReset:
    def test_success_commits_all_four_effects(self, client, app):
        key = _user_with_key(client)
        before = _snapshot(app)
        _forgot(client, 'RkUser', key)
        resp = _reset(client, NEW_PASSWORD)
        assert '/recovery-key' in resp.headers['Location']
        pw, key_row, notes = _snapshot(app)
        assert pw != before[0]                                  # password changed
        assert key_row[1] != before[1][1]                       # new key hash stored
        assert not verify_recovery_key(key_row[1], key)         # old key gone
        assert notes == before[2] + 1                           # notification added
        new_key, _csrf, _ = _read_key_page(client)
        assert verify_recovery_key(key_row[1], new_key)

    @pytest.mark.parametrize('needle', [
        'DELETE FROM recovery_keys',
        'UPDATE users SET password_hash',
        'INSERT INTO recovery_keys',
        'INSERT INTO notifications',
        'UPDATE notifications SET action_url',
    ])
    def test_failure_at_each_step_rolls_back_everything(self, client, app, needle):
        import app.models as models
        key = _user_with_key(client)
        _forgot(client, 'RkUser', key)
        before = _snapshot(app)

        real_get_db = models.get_db
        with patch.object(models, 'get_db', lambda: _FailingDb(real_get_db(), needle)), \
                patch.dict(app.config, {'PROPAGATE_EXCEPTIONS': True}):
            with pytest.raises(sqlite3.OperationalError):
                _reset_raw(client, app)

        assert _snapshot(app) == before
        # Old password and old key still work; no new key was put in the session.
        with client.session_transaction() as sess:
            assert 'recovery_key_plain' not in sess
        assert '/dashboard' in login_user(client, 'RkUser', PASSWORD).headers['Location']
        client.get('/logout')
        assert '/reset-password' in _forgot(client, 'RkUser', key).headers['Location']

    def test_double_submit_second_fails_first_intact(self, client, app):
        key = _user_with_key(client)
        other = app.test_client()
        _forgot(client, 'RkUser', key)
        _forgot(other, 'RkUser', key)

        first = _reset(client, NEW_PASSWORD)
        assert '/recovery-key' in first.headers['Location']
        after_first = _snapshot(app)

        second = _reset(other, 'OtherPassword789!')
        assert second.status_code == 302 and '/forgot-password' in second.headers['Location']
        assert _snapshot(app) == after_first
        with other.session_transaction() as sess:
            assert 'recovery_key_plain' not in sess

        client.get('/logout')
        assert login_user(client, 'RkUser', 'OtherPassword789!').status_code == 200
        assert '/dashboard' in login_user(client, 'RkUser', NEW_PASSWORD).headers['Location']

    def test_security_notification_in_inbox(self, client):
        key = _user_with_key(client)
        _forgot(client, 'RkUser', key)
        _reset(client, NEW_PASSWORD)
        _k, csrf, _ = _read_key_page(client)
        _confirm_key(client, csrf)
        login_user(client, 'RkUser', NEW_PASSWORD)
        html = client.get('/inbox').data.decode()
        assert 'Your password was reset using your recovery key.' in html


def _reset_raw(client, app):
    """POST /reset-password letting exceptions propagate (no 500 handling)."""
    token = get_csrf_token(client.get('/reset-password'))
    return client.post('/reset-password', data={
        'password': NEW_PASSWORD, 'confirm_password': NEW_PASSWORD, 'csrf_token': token,
    })


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

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'scripts'))


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
