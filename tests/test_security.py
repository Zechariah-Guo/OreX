"""Security control tests.

Covers CSRF protection, password hashing, SQL injection resistance,
access control for unauthenticated users, bot login prevention,
rate limiter behaviour, and timing-attack mitigation.
"""

import sqlite3

import pytest

from conftest import get_csrf_token, register_user, login_user

pytestmark = pytest.mark.security


class TestProductionHashing:
    """conftest.py swaps in a cheap hash for speed, so these put Werkzeug's real
    generate_password_hash back and check the app's hashing helpers use its strong
    default (scrypt) rather than passing a weaker method."""

    @pytest.fixture()
    def real_hash(self, monkeypatch):
        import app.models
        import app.totp
        from conftest import _real_generate_password_hash
        monkeypatch.setattr(app.models, 'generate_password_hash', _real_generate_password_hash)
        monkeypatch.setattr(app.totp, 'generate_password_hash', _real_generate_password_hash)

    def _assert_strong(self, stored, secret):
        from werkzeug.security import check_password_hash
        assert stored.startswith('scrypt:'), stored[:30]
        assert secret not in stored
        assert check_password_hash(stored, secret)

    def test_account_passwords(self, app, real_hash):
        from app.database import get_db
        from app.models import create_user, update_password
        with app.app_context():
            user_id = create_user('HashUser', 'SecurePass123!')
            stored = get_db().execute(
                'SELECT password_hash FROM users WHERE id = ?', (user_id,)).fetchone()[0]
            self._assert_strong(stored, 'SecurePass123!')
            update_password(user_id, 'NewSecurePass456!')
            stored = get_db().execute(
                'SELECT password_hash FROM users WHERE id = ?', (user_id,)).fetchone()[0]
            self._assert_strong(stored, 'NewSecurePass456!')

    def test_backup_codes_and_recovery_keys(self, real_hash):
        from app.totp import hash_backup_code, hash_recovery_key
        self._assert_strong(hash_backup_code('AbCd1234'), 'AbCd1234')
        self._assert_strong(hash_recovery_key('ABCD-EFGH-JKLM'), 'ABCDEFGHJKLM')


class TestSecurity:
    """Tests for security controls (Requirement 10)."""

    def test_post_without_csrf_token_returns_400(self, client):
        """TC 10.1: POST to /login without CSRF token returns 400."""
        resp = client.post('/login', data={
            'username': 'anyone',
            'password': 'anything',
        }, follow_redirects=False)

        assert resp.status_code == 400
        # Should NOT contain a login success redirect
        assert b'/dashboard' not in resp.data


    def test_sql_injection_in_username_fails_gracefully(self, client):
        """TC 10.3: SQL injection in username fails gracefully."""
        # Get a valid CSRF token first
        get_resp = client.get('/login')
        token = get_csrf_token(get_resp)

        resp = client.post('/login', data={
            'username': "' OR 1=1 --",
            'password': 'anything',
            'csrf_token': token,
        }, follow_redirects=True)

        # Should NOT be a server error
        assert resp.status_code == 200
        # Should show normal login failure message
        html = resp.data.decode()
        assert 'Invalid username or password.' in html
        assert 'flash-messages' not in html
        # Should NOT contain a database traceback
        assert b'Traceback' not in resp.data
        assert b'sqlite3' not in resp.data

    def test_unauthenticated_dashboard_redirects_to_login(self, client):
        """TC 10.4: Unauthenticated /dashboard redirects to /login."""
        resp = client.get('/dashboard', follow_redirects=False)

        assert resp.status_code == 302
        location = resp.headers.get('Location', '')
        assert '/login' in location

    def test_bot_account_login_fails(self, app, client):
        """TC 10.5: Bot account login fails with 'Invalid username or password.'"""
        # Create bot accounts in the database
        db_path = app.config['DATABASE_PATH']
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        from app.market.bots import ensure_bots_exist
        ensure_bots_exist(conn, app.config['DEFAULT_BALANCE'])
        conn.close()

        # Ensure client is logged out before attempting bot login
        client.get('/logout')

        # Attempt login with a bot username
        resp = login_user(client, 'SteveBot', 'anypassword')
        html = resp.data.decode()
        assert 'Invalid username or password.' in html
        assert 'flash-messages' not in html


    def test_nonexistent_user_returns_same_error_as_wrong_password(self, client):
        """TC 10.7: Login with nonexistent username returns the same error
        message as a wrong password to prevent username enumeration."""
        # Register a real user
        register_user(client, 'RealUser', 'Password123!')
        client.get('/logout')

        # Attempt login with nonexistent username
        resp_nonexistent = login_user(client, 'NoSuchUser', 'Password123!')
        # Attempt login with real username but wrong password
        resp_wrong_pass = login_user(client, 'RealUser', 'WrongPass123!')

        html_nonexistent = resp_nonexistent.data.decode()
        html_wrong_pass = resp_wrong_pass.data.decode()

        # Both must return the same generic error message
        assert 'Invalid username or password.' in html_nonexistent
        assert 'Invalid username or password.' in html_wrong_pass
