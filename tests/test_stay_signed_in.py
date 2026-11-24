"""Tests for 'Stay signed in': the remember cookie and per-user session versions.

A remember cookie is issued only when the Login box is ticked (registration always
remembers). The choice survives the 2FA step. Changing the password, resetting via
the recovery key or the admin script, resetting the account and deleting it all
invalidate every other session and remember cookie for that user, while a player
who changes their own password in Settings stays signed in on that device.
"""

import os
import re
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

import pyotp
import pytest
from flask import Flask

from app.database import init_db
from app.database import get_instance_id
from app.models import load_session_user
from conftest import get_csrf_token, register_user
from test_2fa_login_integration import _setup_user_with_2fa
from test_recovery_key import NEW_PASSWORD, PASSWORD, _forgot, _register, _reset

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'scripts', 'admin'))

SRC_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'src')


def remember_cookie(response):
    """The Set-Cookie header that sets a non-empty remember_token, or None."""
    for header in response.headers.getlist('Set-Cookie'):
        if header.startswith('remember_token=') and not header.startswith('remember_token=;'):
            return header
    return None


def remember_cleared(response):
    return any(h.startswith('remember_token=;') for h in response.headers.getlist('Set-Cookie'))


def login(client, username='RkUser', password=PASSWORD, remember=True):
    token = get_csrf_token(client.get('/login'))
    data = {'username': username, 'password': password, 'csrf_token': token}
    if remember:
        data['remember'] = '1'
    return client.post('/login', data=data, follow_redirects=False)


def drop_session_keep_cookie(client):
    """Simulate the browser closing: the session cookie goes, the remember cookie stays."""
    with client.session_transaction() as sess:
        sess.clear()


def signed_in(client):
    return client.get('/dashboard').status_code == 200


def signed_out(client):
    resp = client.get('/dashboard')
    return resp.status_code == 302 and '/login' in resp.headers['Location']


def _user(app, username='RkUser'):
    conn = sqlite3.connect(app.config['DATABASE_PATH'])
    try:
        row = conn.execute('SELECT id, session_version FROM users WHERE username = ?',
                           (username,)).fetchone()
    finally:
        conn.close()
    return row


@pytest.fixture()
def two_devices(app):
    """A player signed in with the remember box ticked on two separate clients."""
    first = app.test_client()
    register_user(first, 'RkUser', PASSWORD)
    first.get('/logout')
    a, b = app.test_client(), app.test_client()
    assert login(a).status_code == 302
    assert login(b).status_code == 302
    assert signed_in(a) and signed_in(b)
    return a, b


# --- Login box and the cookie ---------------------------------------------------

class TestRememberCookie:

    def test_box_is_ticked_on_first_load_and_keeps_the_choice_after_an_error(self, client):
        html = client.get('/login').data.decode()
        assert 'name="remember"' in html and 'Stay signed in' in html
        assert re.search(r'name="remember"[^>]*\bchecked\b', html)
        token = get_csrf_token(client.get('/login'))
        bad = client.post('/login', data={'username': 'x', 'password': 'y', 'csrf_token': token})
        assert 'name="remember"' in bad.data.decode()
        assert not re.search(r'name="remember"[^>]*\bchecked\b', bad.data.decode())

    def test_ticked_login_sets_a_30_day_cookie(self, app):
        register_user(app.test_client(), 'RkUser', PASSWORD)
        client = app.test_client()
        header = remember_cookie(login(client, remember=True))
        assert header is not None
        assert 'HttpOnly' in header and 'SameSite=Lax' in header
        assert 'Secure' not in header
        expires = parsedate_to_datetime(
            [p.split('=', 1)[1] for p in header.split('; ') if p.startswith('Expires=')][0])
        left = expires - datetime.now(timezone.utc)
        assert timedelta(days=29, hours=23) < left <= timedelta(days=30, minutes=1)

    def test_unticked_login_sets_no_cookie_and_signs_out_when_the_session_ends(self, app):
        register_user(app.test_client(), 'RkUser', PASSWORD)
        client = app.test_client()
        assert remember_cookie(login(client, remember=False)) is None
        assert signed_in(client)
        drop_session_keep_cookie(client)
        assert signed_out(client)

    def test_ticked_login_survives_the_session_ending(self, app):
        register_user(app.test_client(), 'RkUser', PASSWORD)
        client = app.test_client()
        login(client, remember=True)
        drop_session_keep_cookie(client)
        assert signed_in(client)

    def test_registration_remembers(self, app):
        client = app.test_client()
        assert remember_cookie(register_user(client, 'RkUser', PASSWORD)) is not None
        drop_session_keep_cookie(client)
        assert signed_in(client)

    def test_logout_clears_the_cookie(self, app):
        client = app.test_client()
        register_user(client, 'RkUser', PASSWORD)
        assert remember_cleared(client.get('/logout'))
        drop_session_keep_cookie(client)
        assert signed_out(client)

    def test_secure_flag_follows_the_session_cookie_rule(self, app, monkeypatch):
        assert app.config['REMEMBER_COOKIE_SECURE'] == app.config['SESSION_COOKIE_SECURE'] is False
        from app import create_app
        monkeypatch.setenv('SESSION_COOKIE_SECURE', '1')
        other = create_app({'TESTING': True, 'DATABASE_PATH': app.config['DATABASE_PATH'],
                            'SECRET_KEY': 'test-secret-key'})
        assert other.config['REMEMBER_COOKIE_SECURE'] is True
        assert other.config['REMEMBER_COOKIE_DURATION'] == timedelta(days=30)
        assert other.config['REMEMBER_COOKIE_SAMESITE'] == 'Lax'
        assert other.config['REMEMBER_COOKIE_HTTPONLY'] is True


# --- The choice survives the 2FA step -----------------------------------------------

class TestRememberThrough2FA:

    def _challenge_token(self, client):
        return get_csrf_token(client.get('/login/2fa'))

    @pytest.mark.parametrize('ticked', [True, False])
    def test_totp_step(self, app, ticked):
        _uid, secret, _codes = _setup_user_with_2fa(app.test_client(), app)
        client = app.test_client()
        assert '/login/2fa' in login(client, 'TwoFAUser', PASSWORD, remember=ticked).headers['Location']
        resp = client.post('/login/2fa', data={'code': pyotp.TOTP(secret).now(),
                                               'csrf_token': self._challenge_token(client)})
        assert '/dashboard' in resp.headers['Location']
        assert (remember_cookie(resp) is not None) is ticked
        with client.session_transaction() as sess:
            assert 'pending_2fa_remember' not in sess and 'pending_2fa_user_id' not in sess

    @pytest.mark.parametrize('ticked', [True, False])
    def test_backup_code_step(self, app, ticked):
        _uid, _secret, codes = _setup_user_with_2fa(app.test_client(), app)
        client = app.test_client()
        login(client, 'TwoFAUser', PASSWORD, remember=ticked)
        resp = client.post('/login/2fa/backup', data={'backup_code': codes[0],
                                                      'csrf_token': self._challenge_token(client)})
        assert '/dashboard' in resp.headers['Location']
        assert (remember_cookie(resp) is not None) is ticked


# --- Everything that changes credentials signs the other devices out --------------

class TestSessionVersion:

    def test_settings_password_change_keeps_this_device_and_drops_the_other(self, app, two_devices):
        a, b = two_devices
        token = get_csrf_token(a.get('/settings'))
        resp = a.post('/settings/password', data={
            'current_password': PASSWORD, 'new_password': NEW_PASSWORD,
            'confirm_password': NEW_PASSWORD, 'csrf_token': token})
        assert resp.status_code == 302 and '/settings' in resp.headers['Location']
        assert remember_cookie(resp) is not None          # this device keeps remembering
        assert _user(app)[1] == 1
        assert signed_in(a)
        drop_session_keep_cookie(a)
        assert signed_in(a)                                # its new remember cookie works
        assert signed_out(b)                               # session and old cookie are dead
        drop_session_keep_cookie(b)
        assert signed_out(b)                               # old remember cookie alone is dead too

    def test_settings_password_change_without_remember_stays_without_it(self, app):
        register_user(app.test_client(), 'RkUser', PASSWORD)
        a = app.test_client()
        login(a, remember=False)
        token = get_csrf_token(a.get('/settings'))
        resp = a.post('/settings/password', data={
            'current_password': PASSWORD, 'new_password': NEW_PASSWORD,
            'confirm_password': NEW_PASSWORD, 'csrf_token': token})
        assert remember_cookie(resp) is None
        assert signed_in(a)

    def test_recovery_key_reset_signs_every_device_out(self, app):
        first = app.test_client()
        resp, key, _ = _register(first)
        assert '/dashboard' in resp.headers['Location']
        first.get('/logout')
        a, b = app.test_client(), app.test_client()
        login(a)
        login(b)
        stranger = app.test_client()
        assert _forgot(stranger, 'RkUser', key).status_code == 302
        assert '/login' in _reset(stranger)[0].headers['Location']
        assert _user(app)[1] == 1
        assert signed_out(a) and signed_out(b)
        drop_session_keep_cookie(a)
        assert signed_out(a)

    def test_admin_script_reset_signs_every_device_out(self, app, two_devices):
        import reset_password as script
        a, b = two_devices
        script.reset_password('RkUser', NEW_PASSWORD, app=app)
        assert _user(app)[1] == 1
        assert signed_out(a) and signed_out(b)
        drop_session_keep_cookie(a)
        assert signed_out(a)

    def test_account_reset_keeps_this_device_and_drops_the_other(self, app, two_devices):
        a, b = two_devices
        token = get_csrf_token(a.get('/settings/reset'))
        resp = a.post('/settings/reset', data={'confirmation': 'RkUser', 'csrf_token': token})
        assert resp.status_code == 302
        assert _user(app)[1] == 1
        assert signed_in(a)
        assert signed_out(b)
        drop_session_keep_cookie(b)
        assert signed_out(b)

    def test_sign_out_others_keeps_this_device_and_drops_the_other(self, app, two_devices):
        a, b = two_devices
        token = get_csrf_token(a.get('/settings'))
        resp = a.post('/settings/sign-out-others', data={'csrf_token': token})
        assert resp.status_code == 302 and resp.headers['Location'].endswith('/settings#account')
        assert remember_cookie(resp) is not None          # this device keeps remembering
        assert _user(app)[1] == 1
        assert 'Signed out of all other devices.' in a.get('/settings').data.decode()
        assert signed_in(a)
        drop_session_keep_cookie(a)
        assert signed_in(a)                                # its new remember cookie works
        assert signed_out(b)                               # session and old cookie are dead
        drop_session_keep_cookie(b)
        assert signed_out(b)                               # old remember cookie alone is dead too

    def test_sign_out_others_without_remember_stays_without_it(self, app):
        register_user(app.test_client(), 'RkUser', PASSWORD)
        a = app.test_client()
        login(a, remember=False)
        token = get_csrf_token(a.get('/settings'))
        resp = a.post('/settings/sign-out-others', data={'csrf_token': token})
        assert remember_cookie(resp) is None
        assert signed_in(a)

    def test_sign_out_others_needs_a_csrf_token_and_a_login(self, app, two_devices):
        a, b = two_devices
        assert a.post('/settings/sign-out-others').status_code == 400
        assert _user(app)[1] == 0 and signed_in(b)
        anonymous = app.test_client()
        token = get_csrf_token(anonymous.get('/login'))
        resp = anonymous.post('/settings/sign-out-others', data={'csrf_token': token})
        assert resp.status_code == 302 and '/login' in resp.headers['Location']
        assert _user(app)[1] == 0 and signed_in(b)

    def test_account_deletion_drops_the_other_device(self, app, two_devices):
        a, b = two_devices
        token = get_csrf_token(a.get('/settings/delete'))
        resp = a.post('/settings/delete', data={'confirmation': 'RkUser', 'csrf_token': token})
        assert resp.status_code == 302
        assert _user(app) is None
        assert remember_cleared(resp)
        assert signed_out(a) and signed_out(b)
        drop_session_keep_cookie(b)
        assert signed_out(b)

    def test_loader_checks_the_version(self, app):
        register_user(app.test_client(), 'RkUser', PASSWORD)
        uid = _user(app)[0]
        with app.app_context():
            iid = get_instance_id()
            assert iid
            assert load_session_user(f'{uid}:0:{iid}').username == 'RkUser'
            assert load_session_user(f'{uid}:0') is None                # cookie from before instance ids
            assert load_session_user(str(uid)) is None
            assert load_session_user(f'{uid}:0:other') is None          # cookie from another database
            assert load_session_user(f'{uid}:1:{iid}') is None
            assert load_session_user(f'{uid + 1}:0:{iid}') is None
            for junk in ('', 'abc', f'{uid}:x:{iid}', ':', '1:2:3', f'{uid}:0:{iid}:x'):
                assert load_session_user(junk) is None
        conn = sqlite3.connect(app.config['DATABASE_PATH'])
        conn.execute('UPDATE users SET session_version = 3 WHERE id = ?', (uid,))
        conn.commit()
        conn.close()
        with app.app_context():
            iid = get_instance_id()
            assert load_session_user(f'{uid}:0:{iid}') is None
            assert load_session_user(f'{uid}:3:{iid}').session_version == 3
            assert load_session_user(f'{uid}:3:{iid}').get_id() == f'{uid}:3:{iid}'


# --- Existing databases -----------------------------------------------------------------

