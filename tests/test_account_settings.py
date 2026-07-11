"""Account settings test module for OreX.

Covers password change validation and account reset flows.
"""

import sqlite3

import pytest

from conftest import get_csrf_token, register_user, login_user

pytestmark = pytest.mark.account_settings


class TestAccountSettings:
    """Tests for account settings — maps to Testing_Log.md Account Settings section."""

    def test_valid_password_change(self, authenticated_client, app):
        """TC: valid password change succeeds, new password works, old fails."""
        # Get the settings page for CSRF token
        settings_resp = authenticated_client.get('/settings')
        token = get_csrf_token(settings_resp)

        # Change password from Password123! to NewPassword456!
        response = authenticated_client.post('/settings/password', data={
            'current_password': 'Password123!',
            'new_password': 'NewPassword456!',
            'confirm_password': 'NewPassword456!',
            'csrf_token': token,
        }, follow_redirects=True)

        assert response.status_code == 200
        assert b'Password updated successfully.' in response.data

        # Log out to test new credentials
        authenticated_client.get('/logout')

        # Login with the new password should succeed
        new_pass_resp = login_user(authenticated_client, 'TestUser1', 'NewPassword456!')
        assert new_pass_resp.status_code == 302
        assert '/dashboard' in new_pass_resp.headers['Location']

        # Log out and attempt login with old password should fail
        authenticated_client.get('/logout')
        old_pass_resp = login_user(authenticated_client, 'TestUser1', 'Password123!')
        assert old_pass_resp.status_code == 200
        assert b'Invalid username or password.' in old_pass_resp.data

    def test_incorrect_current_password(self, authenticated_client):
        """TC: incorrect current password returns 'Current password is incorrect.'"""
        settings_resp = authenticated_client.get('/settings')
        token = get_csrf_token(settings_resp)

        response = authenticated_client.post('/settings/password', data={
            'current_password': 'WrongPassword1!',
            'new_password': 'NewPassword456!',
            'confirm_password': 'NewPassword456!',
            'csrf_token': token,
        }, follow_redirects=True)

        assert response.status_code == 200
        assert b'Current password is incorrect.' in response.data

    def test_mismatched_new_passwords(self, authenticated_client):
        """TC: mismatched new passwords returns 'New passwords do not match.'"""
        settings_resp = authenticated_client.get('/settings')
        token = get_csrf_token(settings_resp)

        response = authenticated_client.post('/settings/password', data={
            'current_password': 'Password123!',
            'new_password': 'NewPassword456!',
            'confirm_password': 'DifferentPassword789!',
            'csrf_token': token,
        }, follow_redirects=True)

        assert response.status_code == 200
        assert b'New passwords do not match.' in response.data

    @pytest.mark.parametrize('new_password,expected_phrases', [
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
    def test_password_strength_requirements(self, authenticated_client, new_password, expected_phrases):
        """TC: weak new passwords return the specific complexity message."""
        settings_resp = authenticated_client.get('/settings')
        token = get_csrf_token(settings_resp)

        response = authenticated_client.post('/settings/password', data={
            'current_password': 'Password123!',
            'new_password': new_password,
            'confirm_password': new_password,
            'csrf_token': token,
        }, follow_redirects=True)

        assert response.status_code == 200
        html = response.data.decode()
        for phrase in expected_phrases:
            assert phrase in html
        assert html.index('id="new_password"') < html.index('form-error')

    def test_valid_account_reset(self, authenticated_client, app):
        """TC: valid reset confirmation restores balance, deletes holdings, archives transactions."""
        # First, execute a buy trade to create a holding and transaction
        # Step 1: POST from market page to get trade confirmation page
        market_resp = authenticated_client.get('/market/1')
        token = get_csrf_token(market_resp)
        confirm_resp = authenticated_client.post('/trade/buy/1', data={
            'quantity': '5',
            'csrf_token': token,
        }, follow_redirects=True)

        # Step 2: Confirm the trade
        token = get_csrf_token(confirm_resp)
        authenticated_client.post('/trade/buy/1', data={
            'quantity': '5',
            'confirmed': '1',
            'csrf_token': token,
        }, follow_redirects=True)

        # Verify holding and transaction exist before reset
        conn = sqlite3.connect(app.config['DATABASE_PATH'])
        conn.row_factory = sqlite3.Row
        user_row = conn.execute(
            "SELECT id, balance FROM users WHERE username = ?", ('TestUser1',)
        ).fetchone()
        user_id = user_row['id']

        holdings_before = conn.execute(
            "SELECT COUNT(*) as cnt FROM holdings WHERE user_id = ?", (user_id,)
        ).fetchone()['cnt']
        assert holdings_before > 0, "Expected at least one holding before reset"

        transactions_before = conn.execute(
            "SELECT COUNT(*) as cnt FROM transactions WHERE user_id = ? AND archived = 0",
            (user_id,)
        ).fetchone()['cnt']
        assert transactions_before > 0, "Expected at least one active transaction before reset"
        conn.close()

        # Now perform the account reset
        reset_page = authenticated_client.get('/settings/reset')
        token = get_csrf_token(reset_page)

        response = authenticated_client.post('/settings/reset', data={
            'confirmation': 'TestUser1',
            'csrf_token': token,
        }, follow_redirects=True)

        assert response.status_code == 200
        assert b'Account has been reset' in response.data

        # Verify reset effects in database
        conn = sqlite3.connect(app.config['DATABASE_PATH'])
        conn.row_factory = sqlite3.Row

        # Balance should be restored to 10000
        user_after = conn.execute(
            "SELECT balance FROM users WHERE id = ?", (user_id,)
        ).fetchone()
        assert user_after['balance'] == 10000.00

        # Holdings should be deleted
        holdings_after = conn.execute(
            "SELECT COUNT(*) as cnt FROM holdings WHERE user_id = ?", (user_id,)
        ).fetchone()['cnt']
        assert holdings_after == 0

        # Transactions should be archived (archived = 1)
        active_transactions = conn.execute(
            "SELECT COUNT(*) as cnt FROM transactions WHERE user_id = ? AND archived = 0",
            (user_id,)
        ).fetchone()['cnt']
        assert active_transactions == 0

        archived_transactions = conn.execute(
            "SELECT COUNT(*) as cnt FROM transactions WHERE user_id = ? AND archived = 1",
            (user_id,)
        ).fetchone()['cnt']
        assert archived_transactions > 0

        conn.close()

    def test_incorrect_username_confirmation(self, authenticated_client):
        """TC: incorrect username confirmation returns 'Username confirmation does not match.'"""
        reset_page = authenticated_client.get('/settings/reset')
        token = get_csrf_token(reset_page)

        response = authenticated_client.post('/settings/reset', data={
            'confirmation': 'WrongUsername',
            'csrf_token': token,
        }, follow_redirects=True)

        assert response.status_code == 200
        assert b'Username confirmation does not match.' in response.data

    def test_valid_account_deletion(self, authenticated_client, app):
        """TC: valid deletion confirmation removes all user data and logs out."""
        # First, execute a buy trade to create holdings and transactions
        market_resp = authenticated_client.get('/market/1')
        token = get_csrf_token(market_resp)
        confirm_resp = authenticated_client.post('/trade/buy/1', data={
            'quantity': '5',
            'csrf_token': token,
        }, follow_redirects=True)

        token = get_csrf_token(confirm_resp)
        authenticated_client.post('/trade/buy/1', data={
            'quantity': '5',
            'confirmed': '1',
            'csrf_token': token,
        }, follow_redirects=True)

        # Verify user data exists before deletion
        conn = sqlite3.connect(app.config['DATABASE_PATH'])
        conn.row_factory = sqlite3.Row
        user_row = conn.execute(
            "SELECT id FROM users WHERE username = ?", ('TestUser1',)
        ).fetchone()
        user_id = user_row['id']

        holdings_before = conn.execute(
            "SELECT COUNT(*) as cnt FROM holdings WHERE user_id = ?", (user_id,)
        ).fetchone()['cnt']
        assert holdings_before > 0

        transactions_before = conn.execute(
            "SELECT COUNT(*) as cnt FROM transactions WHERE user_id = ?", (user_id,)
        ).fetchone()['cnt']
        assert transactions_before > 0
        conn.close()

        # Perform account deletion
        delete_page = authenticated_client.get('/settings/delete')
        token = get_csrf_token(delete_page)

        response = authenticated_client.post('/settings/delete', data={
            'confirmation': 'TestUser1',
            'csrf_token': token,
        }, follow_redirects=True)

        assert response.status_code == 200
        assert b'Your account has been permanently deleted.' in response.data

        # Verify all user data is removed from database
        conn = sqlite3.connect(app.config['DATABASE_PATH'])
        conn.row_factory = sqlite3.Row

        user_after = conn.execute(
            "SELECT COUNT(*) as cnt FROM users WHERE id = ?", (user_id,)
        ).fetchone()['cnt']
        assert user_after == 0

        holdings_after = conn.execute(
            "SELECT COUNT(*) as cnt FROM holdings WHERE user_id = ?", (user_id,)
        ).fetchone()['cnt']
        assert holdings_after == 0

        transactions_after = conn.execute(
            "SELECT COUNT(*) as cnt FROM transactions WHERE user_id = ?", (user_id,)
        ).fetchone()['cnt']
        assert transactions_after == 0

        conn.close()

        # Verify user is logged out (accessing protected route redirects to login)
        dashboard_resp = authenticated_client.get('/dashboard')
        assert dashboard_resp.status_code == 302
        assert '/login' in dashboard_resp.headers['Location']

    def test_incorrect_deletion_confirmation(self, authenticated_client):
        """TC: incorrect username confirmation for deletion returns error, no changes made."""
        delete_page = authenticated_client.get('/settings/delete')
        token = get_csrf_token(delete_page)

        response = authenticated_client.post('/settings/delete', data={
            'confirmation': 'WrongUsername',
            'csrf_token': token,
        }, follow_redirects=True)

        assert response.status_code == 200
        assert b'Username confirmation does not match. Account was not deleted.' in response.data

        # Verify user still exists
        settings_resp = authenticated_client.get('/settings')
        assert settings_resp.status_code == 200
