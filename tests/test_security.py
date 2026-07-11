"""Security control tests.

Covers CSRF protection, password hashing, SQL injection resistance,
access control for unauthenticated users, bot login prevention,
rate limiter behaviour, and timing-attack mitigation.
"""

import sqlite3

import pytest

from conftest import get_csrf_token, register_user, login_user

pytestmark = pytest.mark.security


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

    def test_password_hash_uses_werkzeug_prefix(self, app, client):
        """TC 10.2: Registered user's password_hash uses Werkzeug hashing."""
        password = 'SecurePass123!'
        register_user(client, 'HashTestUser', password)

        # Query database directly for the password_hash
        db_path = app.config['DATABASE_PATH']
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT password_hash FROM users WHERE username = ?",
            ('HashTestUser',)
        ).fetchone()
        conn.close()

        assert row is not None
        password_hash = row['password_hash']

        # Must start with a recognized Werkzeug hash prefix
        assert password_hash.startswith('pbkdf2:sha256:') or \
            password_hash.startswith('scrypt:'), \
            f"password_hash does not start with recognized prefix: {password_hash[:30]}"

        # Must NOT contain the plaintext password
        assert password not in password_hash

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

    def test_rate_limiter_blocks_after_max_attempts(self, app, client):
        """TC 10.6: Rate limiter counts attempts; 6th attempt is blocked."""
        # Register a valid user
        register_user(client, 'RateLimitUser', 'validpass123')

        # Log out (registration auto-logs in)
        client.get('/logout')

        # Make 5 failed login attempts (RATE_LIMIT_MAX = 5)
        for i in range(5):
            resp = login_user(client, 'RateLimitUser', 'wrongpassword')
            # Should get "Invalid username or password." (not rate-limited yet)
            html = resp.data.decode()
            assert 'Invalid username or password.' in html or 'Too many login attempts' in html

        # 6th attempt should be rate-limited regardless of correct credentials
        resp = login_user(client, 'RateLimitUser', 'validpass123')

        html = resp.data.decode()
        assert 'Too many login attempts. Please try again in ' in html
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


# ---------------------------------------------------------------------------
# Property-Based Tests
# ---------------------------------------------------------------------------

import itertools

from hypothesis import given, settings
from hypothesis import strategies as st

from conftest import register_user


class TestSecurityProperties:
    """Property-based tests for security controls."""

    # Feature: orex-test-suite, Property 10: Password hashing correctness
    _counter = itertools.count()

    @settings(max_examples=100, deadline=None)
    @given(
        password=st.text(
            min_size=8,
            max_size=50,
            alphabet=st.characters(whitelist_categories=('L', 'N', 'P')),
        )
    )
    def test_password_hashing_correctness(self, app, client, password):
        """**Validates: Requirements 10.2**

        For any non-empty password string, after user registration the stored
        password_hash starts with a recognized Werkzeug hash prefix and does
        NOT contain the plaintext password as a substring.
        """
        username = f"PropUser{next(TestSecurityProperties._counter)}"
        password = f"Aa1!{password}"

        # Ensure logged out before registering a new user
        client.get('/logout')
        register_user(client, username, password)

        # Query database directly for the stored password_hash
        db_path = app.config['DATABASE_PATH']
        import sqlite3
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT password_hash FROM users WHERE username = ?",
            (username,),
        ).fetchone()
        conn.close()

        assert row is not None, f"User {username} was not created in the database"
        password_hash = row['password_hash']

        # Must start with a recognized Werkzeug hash prefix
        assert password_hash.startswith('pbkdf2:sha256:') or \
            password_hash.startswith('scrypt:'), \
            f"password_hash does not start with recognized prefix: {password_hash[:30]}"

        # Must NOT contain the plaintext password as a substring
        assert password not in password_hash, \
            "password_hash contains the plaintext password"
