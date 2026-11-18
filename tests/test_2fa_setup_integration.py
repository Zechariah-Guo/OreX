"""Integration tests for 2FA setup and disable flows.

Validates end-to-end behaviour of enabling, confirming, and disabling
two-factor authentication, as well as interactions with account reset
and account deletion.

Requirements: 1.3, 2.1, 2.2, 2.3, 3.1, 3.2, 8.2, 8.3, 10.1, 10.3
"""

import re
import sqlite3

import pyotp
import pytest

from conftest import get_csrf_token, register_user, login_user

pytestmark = pytest.mark.integration_2fa


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_manual_key(response):
    """Extract the manual_key (TOTP secret) from the setup page HTML."""
    html = response.data.decode()
    match = re.search(r'id="manual-key"[^>]*value="([^"]+)"', html)
    if not match:
        raise ValueError('Could not find manual-key in setup response.')
    return match.group(1)


def _setup_2fa(client):
    """Run the full 2FA setup flow and return (secret, backup_codes_response).

    Assumes the client is already authenticated.
    """
    # Initiate setup
    settings_resp = client.get('/settings')
    token = get_csrf_token(settings_resp)
    setup_resp = client.post('/settings/2fa/setup', data={
        'csrf_token': token,
    }, follow_redirects=True)
    assert setup_resp.status_code == 200

    secret = _get_manual_key(setup_resp)

    # Confirm with a valid TOTP code
    valid_code = pyotp.TOTP(secret).now()
    token = get_csrf_token(setup_resp)
    confirm_resp = client.post('/settings/2fa/confirm', data={
        'code': valid_code,
        'csrf_token': token,
    }, follow_redirects=True)
    assert confirm_resp.status_code == 200

    return secret, confirm_resp


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestEnable2FA:
    """End-to-end tests for 2FA setup → confirm → backup codes display."""

    def test_enable_2fa_end_to_end(self, authenticated_client):
        """Setup → confirm with valid code → backup codes displayed.

        Validates: Requirements 1.3, 2.1, 2.2, 3.1, 3.2
        """
        secret, confirm_resp = _setup_2fa(authenticated_client)

        html = confirm_resp.data.decode()
        # Backup codes should be displayed
        assert 'Save your backup codes now' in html
        # There should be exactly 8 backup code items
        codes = re.findall(r'<code>([A-Za-z0-9]{8})</code>', html)
        assert len(codes) == 8
        # All codes should be unique
        assert len(set(codes)) == 8
        # Success flash
        assert 'Two-factor authentication is now enabled' in html

    def test_setup_rejects_invalid_code_without_regenerating_secret(self, authenticated_client):
        """Invalid TOTP code at confirm step re-renders with SAME secret.

        Validates: Requirements 2.3
        """
        # Initiate setup
        settings_resp = authenticated_client.get('/settings')
        token = get_csrf_token(settings_resp)
        setup_resp = authenticated_client.post('/settings/2fa/setup', data={
            'csrf_token': token,
        }, follow_redirects=True)
        assert setup_resp.status_code == 200

        secret = _get_manual_key(setup_resp)

        # Submit an invalid code
        token = get_csrf_token(setup_resp)
        invalid_resp = authenticated_client.post('/settings/2fa/confirm', data={
            'code': '000000',
            'csrf_token': token,
        }, follow_redirects=True)
        assert invalid_resp.status_code == 200

        html = invalid_resp.data.decode()
        assert 'Invalid authentication code' in html

        # The secret should be the SAME (no regeneration)
        same_secret = _get_manual_key(invalid_resp)
        assert same_secret == secret

        # Now confirm with a valid code — should still work
        valid_code = pyotp.TOTP(secret).now()
        token = get_csrf_token(invalid_resp)
        confirm_resp = authenticated_client.post('/settings/2fa/confirm', data={
            'code': valid_code,
            'csrf_token': token,
        }, follow_redirects=True)
        assert confirm_resp.status_code == 200
        assert 'Two-factor authentication is now enabled' in confirm_resp.data.decode()


class TestDisable2FA:
    """End-to-end tests for disabling 2FA."""

    def test_disable_2fa_end_to_end(self, authenticated_client):
        """Enter valid code → 2FA removed → login without challenge.

        Validates: Requirements 8.2, 8.3
        """
        secret, _ = _setup_2fa(authenticated_client)

        # Disable 2FA with a valid TOTP code
        settings_resp = authenticated_client.get('/settings')
        token = get_csrf_token(settings_resp)
        disable_code = pyotp.TOTP(secret).now()
        disable_resp = authenticated_client.post('/settings/2fa/disable', data={
            'code': disable_code,
            'csrf_token': token,
        }, follow_redirects=True)
        assert disable_resp.status_code == 200
        assert 'Two-factor authentication has been disabled' in disable_resp.data.decode()

        # Log out and log back in — should NOT redirect to /login/2fa
        authenticated_client.get('/logout')
        login_resp = login_user(authenticated_client, 'TestUser1', 'Password123!')
        assert login_resp.status_code == 302
        assert '/dashboard' in login_resp.headers['Location']


class TestAccountResetPreserves2FA:
    """Test that account reset does NOT touch 2FA configuration."""

    def test_account_reset_preserves_2fa(self, authenticated_client, app):
        """After account reset, login still requires 2FA challenge.

        Validates: Requirements 10.1, 10.3 (preservation aspect)
        """
        secret, _ = _setup_2fa(authenticated_client)

        # Perform account reset
        reset_page = authenticated_client.get('/settings/reset')
        token = get_csrf_token(reset_page)
        reset_resp = authenticated_client.post('/settings/reset', data={
            'confirmation': 'TestUser1',
            'csrf_token': token,
        }, follow_redirects=True)
        assert reset_resp.status_code == 200
        assert b'Account has been reset' in reset_resp.data

        # Log out and try to log back in — should redirect to 2FA challenge
        authenticated_client.get('/logout')
        login_resp = login_user(authenticated_client, 'TestUser1', 'Password123!')
        assert login_resp.status_code == 302
        assert '/login/2fa' in login_resp.headers['Location']

        # Complete the 2FA challenge to verify the secret still works
        challenge_page = authenticated_client.get('/login/2fa')
        assert challenge_page.status_code == 200
        token = get_csrf_token(challenge_page)
        valid_code = pyotp.TOTP(secret).now()
        verify_resp = authenticated_client.post('/login/2fa', data={
            'code': valid_code,
            'csrf_token': token,
        }, follow_redirects=False)
        assert verify_resp.status_code == 302
        assert '/dashboard' in verify_resp.headers['Location']


class TestAccountDeleteRemoves2FA:
    """Test that account deletion removes all 2FA data."""

    def test_account_delete_removes_all_2fa_data(self, authenticated_client, app):
        """Account deletion removes user row AND backup_codes rows.

        Validates: Requirements 10.3
        """
        secret, _ = _setup_2fa(authenticated_client)

        # Determine user_id before deletion
        conn = sqlite3.connect(app.config['DATABASE_PATH'])
        conn.row_factory = sqlite3.Row
        user_row = conn.execute(
            "SELECT id FROM users WHERE username = ?", ('TestUser1',)
        ).fetchone()
        user_id = user_row['id']

        # Verify backup_codes exist
        code_count = conn.execute(
            "SELECT COUNT(*) as cnt FROM backup_codes WHERE user_id = ?",
            (user_id,)
        ).fetchone()['cnt']
        assert code_count == 8, "Expected 8 backup codes before deletion"
        conn.close()

        # Delete account
        delete_page = authenticated_client.get('/settings/delete')
        token = get_csrf_token(delete_page)
        delete_resp = authenticated_client.post('/settings/delete', data={
            'confirmation': 'TestUser1',
            'csrf_token': token,
        }, follow_redirects=True)
        assert delete_resp.status_code == 200
        assert b'Your account has been permanently deleted.' in delete_resp.data

        # Verify no user row and no orphaned backup_codes
        conn = sqlite3.connect(app.config['DATABASE_PATH'])
        conn.row_factory = sqlite3.Row

        user_after = conn.execute(
            "SELECT COUNT(*) as cnt FROM users WHERE id = ?", (user_id,)
        ).fetchone()['cnt']
        assert user_after == 0, "User row should be deleted"

        codes_after = conn.execute(
            "SELECT COUNT(*) as cnt FROM backup_codes WHERE user_id = ?",
            (user_id,)
        ).fetchone()['cnt']
        assert codes_after == 0, "No orphaned backup_codes should remain"
        conn.close()
