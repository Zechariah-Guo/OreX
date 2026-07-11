"""Authentication test module for OreX.

Covers registration, login, rate limiting, and logout flows.
"""

import sqlite3

import pytest

from conftest import get_csrf_token, register_user, login_user

pytestmark = pytest.mark.authentication


class TestAuthentication:
    """Tests for authentication — maps to Testing_Log.md Authentication section."""

    def test_successful_registration(self, client, app):
        """TC: successful registration redirects to /dashboard with user row and balance 10000.00."""
        response = register_user(client, 'TestUser1', 'Password123!')

        # Should redirect to /dashboard
        assert response.status_code == 302
        assert '/dashboard' in response.headers['Location']

        # Verify user row exists in the database with correct balance
        conn = sqlite3.connect(app.config['DATABASE_PATH'])
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT username, balance FROM users WHERE username = ?",
            ('TestUser1',)
        ).fetchone()
        conn.close()

        assert row is not None
        assert row['username'] == 'TestUser1'
        assert row['balance'] == 10000.00

    def test_duplicate_username(self, client):
        """TC: duplicate username returns 'That username is already taken.'"""
        # Register the user first
        register_user(client, 'TestUser1', 'Password123!')

        # Log out so we can register again
        client.get('/logout')

        # Attempt to register with the same username
        response = register_user(client, 'TestUser1', 'Password123!')

        assert response.status_code == 200
        assert b'That username is already taken.' in response.data

    def test_short_username(self, client):
        """TC: short username (<3 chars) returns appropriate error."""
        get_resp = client.get('/register')
        token = get_csrf_token(get_resp)

        response = client.post('/register', data={
            'username': 'AB',
            'password': 'Password123!',
            'confirm_password': 'Password123!',
            'csrf_token': token,
        }, follow_redirects=False)

        assert response.status_code == 200
        assert b'Username must be at least 3 characters.' in response.data

    def test_invalid_characters_in_username(self, client):
        """TC: invalid characters in username returns appropriate error."""
        get_resp = client.get('/register')
        token = get_csrf_token(get_resp)

        response = client.post('/register', data={
            'username': 'Test User!',
            'password': 'Password123!',
            'confirm_password': 'Password123!',
            'csrf_token': token,
        }, follow_redirects=False)

        assert response.status_code == 200
        assert b'Username can only contain letters, numbers, and underscores.' in response.data

    @pytest.mark.parametrize('password,expected_message', [
        ('short', [
            'at least 8 characters',
            'at least one number',
            'at least one symbol',
            'at least one uppercase letter',
        ]),
        ('W3ATHEHE', [
            'at least one symbol',
            'at least one lowercase letter',
        ]),
        ('W3@THEHE', [
            'at least one lowercase letter',
        ]),
        ('alllowercase1!', [
            'at least one uppercase letter',
        ]),
        ('ALLUPPERCASE1!', [
            'at least one lowercase letter',
        ]),
        ('NoNumber!', [
            'at least one number',
        ]),
        ('NoSymbol1', [
            'at least one symbol',
        ]),
    ])
    def test_password_strength_requirements(self, client, password, expected_message):
        """TC: weak passwords return the specific complexity message."""
        get_resp = client.get('/register')
        token = get_csrf_token(get_resp)

        response = client.post('/register', data={
            'username': 'TestUser1',
            'password': password,
            'confirm_password': password,
            'csrf_token': token,
        }, follow_redirects=False)

        assert response.status_code == 200
        html = response.data.decode()
        for phrase in expected_message:
            assert phrase in html
        assert html.index('id="password"') < html.index('form-error')

    def test_mismatched_passwords(self, client):
        """TC: mismatched passwords returns 'Passwords do not match.'"""
        get_resp = client.get('/register')
        token = get_csrf_token(get_resp)

        response = client.post('/register', data={
            'username': 'TestUser1',
            'password': 'Password123!',
            'confirm_password': 'Different456!',
            'csrf_token': token,
        }, follow_redirects=False)

        assert response.status_code == 200
        assert b'Passwords do not match.' in response.data

    def test_valid_login(self, client):
        """TC: valid login redirects to /dashboard."""
        # Register the user first
        register_user(client, 'TestUser1', 'Password123!')
        # Log out
        client.get('/logout')

        # Log in with valid credentials
        response = login_user(client, 'TestUser1', 'Password123!')

        assert response.status_code == 302
        assert '/dashboard' in response.headers['Location']

        # Verify subsequent requests to protected routes succeed
        dashboard_resp = client.get('/dashboard')
        assert dashboard_resp.status_code == 200

    def test_invalid_login(self, client):
        """TC: invalid login returns 'Invalid username or password.'"""
        # Register user first so username exists
        register_user(client, 'TestUser1', 'Password123!')
        client.get('/logout')

        # Attempt login with wrong password
        response = login_user(client, 'TestUser1', 'wrongpassword')

        assert response.status_code == 200
        html = response.data.decode()
        assert 'Invalid username or password.' in html
        assert html.index('id="password"') < html.index('form-error')
        assert 'flash-messages' not in html

    def test_rate_limiting(self, client):
        """TC: rate limiting after 5 failures returns an inline retry message."""
        # Register user first
        register_user(client, 'TestUser1', 'Password123!')
        client.get('/logout')

        # Make 5 failed login attempts
        for _ in range(5):
            login_user(client, 'TestUser1', 'wrongpassword')

        # 6th attempt should be rate limited
        response = login_user(client, 'TestUser1', 'Password123!')

        html = response.data.decode()
        assert 'Too many login attempts. Please try again in ' in html
        assert 'flash-messages' not in html
        assert html.index('id="password"') < html.index('form-error')

    def test_logout_redirects_and_invalidates_session(self, client):
        """TC: logout redirects and invalidates session."""
        # Register and login
        register_user(client, 'TestUser1', 'Password123!')

        # Logout
        response = client.get('/logout', follow_redirects=False)

        assert response.status_code == 302

        # Subsequent request to /dashboard should redirect to /login
        dashboard_resp = client.get('/dashboard', follow_redirects=False)
        assert dashboard_resp.status_code == 302
        assert '/login' in dashboard_resp.headers['Location']
