"""Integration tests for the 2FA login challenge flow.

Covers:
- Full login flow: password → redirect to /login/2fa → valid TOTP → dashboard
- Login flow with backup code: password → redirect → valid backup code → dashboard
- Pending session blocks access to authenticated routes
- Expired pending session redirects to login
- Rate limiting shared counter across password and 2FA failures

Requirements: 4.1, 4.2, 4.5, 5.1, 6.1, 6.3, 7.1, 7.2
"""

import time

import pyotp
import pytest

from conftest import get_csrf_token, register_user, login_user
from app.totp import (
    generate_secret,
    encrypt_secret,
    hash_backup_code,
)
from app.models import enable_2fa, store_backup_codes
from app.routes.auth import _login_attempts, _record_attempt

pytestmark = pytest.mark.integration_2fa


def _setup_user_with_2fa(client, app, username='TwoFAUser', password='Password123!'):
    """Register a user and enable 2FA for them.

    Returns (user_id, totp_secret, backup_codes_plaintext).
    """
    import sqlite3

    # Register user
    register_user(client, username, password)
    # Logout so we can test the login flow
    client.get('/logout')

    # Find user in DB
    conn = sqlite3.connect(app.config['DATABASE_PATH'])
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT id FROM users WHERE username = ?", (username,)
    ).fetchone()
    user_id = row['id']
    conn.close()

    # Enable 2FA directly in the DB
    secret = generate_secret()
    encrypted = encrypt_secret(secret, app.config['SECRET_KEY'])

    with app.app_context():
        enable_2fa(user_id, encrypted)
        # Generate and store backup codes
        backup_codes = ['Backup01', 'Backup02', 'Backup03', 'Backup04',
                        'Backup05', 'Backup06', 'Backup07', 'Backup08']
        hashed = [hash_backup_code(c) for c in backup_codes]
        store_backup_codes(user_id, hashed)

    return user_id, secret, backup_codes


class TestLogin2FAFlow:
    """Integration tests for the full 2FA login challenge flow."""

    def test_login_redirects_to_2fa_challenge(self, client, app):
        """Password success with 2FA enabled redirects to /login/2fa (Req 4.1)."""
        _setup_user_with_2fa(client, app)

        response = login_user(client, 'TwoFAUser', 'Password123!')

        assert response.status_code == 302
        assert '/login/2fa' in response.headers['Location']

    def test_full_login_flow_with_totp(self, client, app):
        """Full flow: password → /login/2fa → valid TOTP → dashboard (Req 4.5)."""
        _user_id, secret, _codes = _setup_user_with_2fa(client, app)

        # Step 1: Login with password — should redirect to /login/2fa
        response = login_user(client, 'TwoFAUser', 'Password123!')
        assert response.status_code == 302
        assert '/login/2fa' in response.headers['Location']

        # Step 2: GET the 2FA challenge page
        challenge_resp = client.get('/login/2fa')
        assert challenge_resp.status_code == 200
        csrf_token = get_csrf_token(challenge_resp)

        # Step 3: POST valid TOTP code
        valid_code = pyotp.TOTP(secret).now()
        verify_resp = client.post('/login/2fa', data={
            'code': valid_code,
            'csrf_token': csrf_token,
        }, follow_redirects=False)

        assert verify_resp.status_code == 302
        assert '/dashboard' in verify_resp.headers['Location']

        # Step 4: Verify we can access authenticated routes
        dashboard_resp = client.get('/dashboard')
        assert dashboard_resp.status_code == 200

    def test_full_login_flow_with_backup_code(self, client, app):
        """Full flow: password → /login/2fa → valid backup code → dashboard (Req 5.1)."""
        _user_id, _secret, backup_codes = _setup_user_with_2fa(client, app)

        # Step 1: Login with password
        response = login_user(client, 'TwoFAUser', 'Password123!')
        assert response.status_code == 302
        assert '/login/2fa' in response.headers['Location']

        # Step 2: GET the 2FA challenge page to get CSRF token
        challenge_resp = client.get('/login/2fa')
        assert challenge_resp.status_code == 200
        csrf_token = get_csrf_token(challenge_resp)

        # Step 3: POST valid backup code
        verify_resp = client.post('/login/2fa/backup', data={
            'backup_code': backup_codes[0],
            'csrf_token': csrf_token,
        }, follow_redirects=False)

        assert verify_resp.status_code == 302
        assert '/dashboard' in verify_resp.headers['Location']

        # Step 4: Verify authenticated
        dashboard_resp = client.get('/dashboard')
        assert dashboard_resp.status_code == 200

    def test_invalid_totp_code_rejected(self, client, app):
        """Invalid TOTP code is rejected with error message (Req 4.5)."""
        _setup_user_with_2fa(client, app)

        # Login with password
        login_user(client, 'TwoFAUser', 'Password123!')

        # GET challenge page
        challenge_resp = client.get('/login/2fa')
        csrf_token = get_csrf_token(challenge_resp)

        # POST invalid code
        verify_resp = client.post('/login/2fa', data={
            'code': '000000',
            'csrf_token': csrf_token,
        }, follow_redirects=False)

        assert verify_resp.status_code == 200
        assert b'Invalid authentication code' in verify_resp.data

    def test_invalid_backup_code_rejected(self, client, app):
        """Invalid backup code is rejected with error message (Req 5.1)."""
        _setup_user_with_2fa(client, app)

        # Login with password
        login_user(client, 'TwoFAUser', 'Password123!')

        # GET challenge page
        challenge_resp = client.get('/login/2fa')
        csrf_token = get_csrf_token(challenge_resp)

        # POST invalid backup code
        verify_resp = client.post('/login/2fa/backup', data={
            'backup_code': 'INVALID1',
            'csrf_token': csrf_token,
        }, follow_redirects=False)

        assert verify_resp.status_code == 200
        assert b'Invalid or already-used backup code' in verify_resp.data


class TestPendingSessionSecurity:
    """Tests for pending 2FA session blocking access (Req 4.2, 7.1, 7.2)."""

    def test_pending_session_blocks_authenticated_routes(self, client, app):
        """A pending 2FA session does NOT grant access to authenticated routes (Req 4.2)."""
        _setup_user_with_2fa(client, app)

        # Login with password — creates pending session
        login_user(client, 'TwoFAUser', 'Password123!')

        # Try to access dashboard — should redirect to login
        dashboard_resp = client.get('/dashboard', follow_redirects=False)
        assert dashboard_resp.status_code == 302
        assert '/login' in dashboard_resp.headers['Location']

    def test_expired_pending_session_redirects_to_login(self, client, app):
        """Expired pending session (>= 300s) redirects to login (Req 7.1, 7.2)."""
        _setup_user_with_2fa(client, app)

        # Login with password
        login_user(client, 'TwoFAUser', 'Password123!')

        # Manipulate session to simulate expiry
        with client.session_transaction() as sess:
            sess['pending_2fa_time'] = time.time() - 301

        # GET challenge page — should redirect to login
        challenge_resp = client.get('/login/2fa', follow_redirects=False)
        assert challenge_resp.status_code == 302
        assert '/login' in challenge_resp.headers['Location']

    def test_expired_session_rejects_totp_post(self, client, app):
        """POST to /login/2fa with expired session redirects to login (Req 7.2)."""
        _user_id, secret, _codes = _setup_user_with_2fa(client, app)

        # Login with password
        login_user(client, 'TwoFAUser', 'Password123!')

        # Get CSRF token before expiring session
        challenge_resp = client.get('/login/2fa')
        csrf_token = get_csrf_token(challenge_resp)

        # Expire the session
        with client.session_transaction() as sess:
            sess['pending_2fa_time'] = time.time() - 301

        # POST valid TOTP — should still redirect to login
        valid_code = pyotp.TOTP(secret).now()
        verify_resp = client.post('/login/2fa', data={
            'code': valid_code,
            'csrf_token': csrf_token,
        }, follow_redirects=False)

        assert verify_resp.status_code == 302
        assert '/login' in verify_resp.headers['Location']

    def test_no_pending_session_redirects_to_login(self, client, app):
        """Direct access to /login/2fa without pending session redirects (Req 7.2)."""
        response = client.get('/login/2fa', follow_redirects=False)
        assert response.status_code == 302
        assert '/login' in response.headers['Location']


class TestRateLimitingSharedCounter:
    """Tests for shared rate limit counter across password and 2FA failures (Req 6.1, 6.3)."""

    def test_rate_limit_on_2fa_challenge(self, client, app):
        """2FA challenge is rate limited after 5 failed attempts (Req 6.1)."""
        _user_id, _secret, _codes = _setup_user_with_2fa(client, app)

        # Login with password
        login_user(client, 'TwoFAUser', 'Password123!')

        # Make 5 failed 2FA attempts
        for _ in range(5):
            challenge_resp = client.get('/login/2fa')
            csrf_token = get_csrf_token(challenge_resp)
            client.post('/login/2fa', data={
                'code': '000000',
                'csrf_token': csrf_token,
            }, follow_redirects=False)

        # 6th attempt should be rate limited
        challenge_resp = client.get('/login/2fa')
        csrf_token = get_csrf_token(challenge_resp)
        rate_limited_resp = client.post('/login/2fa', data={
            'code': '000000',
            'csrf_token': csrf_token,
        }, follow_redirects=False)

        assert rate_limited_resp.status_code == 200
        assert b'Too many attempts' in rate_limited_resp.data

    def test_shared_counter_password_and_2fa_failures(self, client, app):
        """Failed password + failed 2FA attempts share the same counter (Req 6.3)."""
        _user_id, _secret, _codes = _setup_user_with_2fa(client, app)

        # Make 3 failed password attempts
        for _ in range(3):
            login_user(client, 'TwoFAUser', 'WrongPassword1!')

        # Login successfully with password (doesn't count as an attempt)
        login_user(client, 'TwoFAUser', 'Password123!')

        # Make 2 more failed 2FA attempts (total = 3 + 2 = 5)
        for _ in range(2):
            challenge_resp = client.get('/login/2fa')
            csrf_token = get_csrf_token(challenge_resp)
            client.post('/login/2fa', data={
                'code': '000000',
                'csrf_token': csrf_token,
            }, follow_redirects=False)

        # Next attempt (6th total) should be rate limited
        challenge_resp = client.get('/login/2fa')
        csrf_token = get_csrf_token(challenge_resp)
        rate_limited_resp = client.post('/login/2fa', data={
            'code': '000000',
            'csrf_token': csrf_token,
        }, follow_redirects=False)

        assert rate_limited_resp.status_code == 200
        assert b'Too many attempts' in rate_limited_resp.data

    def test_rate_limit_on_backup_code_attempts(self, client, app):
        """Backup code failures also count toward shared rate limit (Req 6.3)."""
        _user_id, _secret, _codes = _setup_user_with_2fa(client, app)

        # Login with password
        login_user(client, 'TwoFAUser', 'Password123!')

        # Make 5 failed backup code attempts
        for _ in range(5):
            challenge_resp = client.get('/login/2fa')
            csrf_token = get_csrf_token(challenge_resp)
            client.post('/login/2fa/backup', data={
                'backup_code': 'INVALID1',
                'csrf_token': csrf_token,
            }, follow_redirects=False)

        # 6th attempt should be rate limited
        challenge_resp = client.get('/login/2fa')
        csrf_token = get_csrf_token(challenge_resp)
        rate_limited_resp = client.post('/login/2fa/backup', data={
            'backup_code': 'INVALID1',
            'csrf_token': csrf_token,
        }, follow_redirects=False)

        assert rate_limited_resp.status_code == 200
        assert b'Too many attempts' in rate_limited_resp.data
