"""Unit tests for Advanced Mode settings routes (purchase and toggle).

Covers:
- POST /settings/advanced/purchase: success, insufficient funds, ineligibility, double-purchase
- POST /settings/advanced/toggle: success, cooldown rejection
"""

import sqlite3
from datetime import datetime, timedelta

import pytest

from conftest import get_csrf_token, register_user

pytestmark = pytest.mark.settings_advanced


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_user_id(app, username='TestUser1'):
    """Look up user ID by username."""
    conn = sqlite3.connect(app.config['DATABASE_PATH'])
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone()
    conn.close()
    return row['id']


def _set_user_state(app, username='TestUser1', **kwargs):
    """Directly set user columns in the database for test setup.

    Supported kwargs: balance, advanced_eligible, advanced_purchased,
    advanced_active, advanced_toggled_at.
    """
    if not kwargs:
        return

    conn = sqlite3.connect(app.config['DATABASE_PATH'])
    sets = ', '.join(f'{k} = ?' for k in kwargs)
    values = list(kwargs.values())
    conn.execute(
        f"UPDATE users SET {sets} WHERE username = ?",
        values + [username],
    )
    conn.commit()
    conn.close()


def _get_user_row(app, username='TestUser1'):
    """Fetch the full user row as a dict."""
    conn = sqlite3.connect(app.config['DATABASE_PATH'])
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
    conn.close()
    return dict(row)


# ---------------------------------------------------------------------------
# Purchase endpoint tests
# ---------------------------------------------------------------------------

class TestAdvancedPurchase:
    """Tests for POST /settings/advanced/purchase."""

    def test_purchase_success(self, authenticated_client, app):
        """Eligible user with sufficient balance can purchase Advanced Mode.

        Requirements: 3.1, 3.4
        """
        # Set up: user is eligible, has $60,000 balance
        _set_user_state(app, balance=60000.0, advanced_eligible=1)

        # Get CSRF token from settings page
        settings_resp = authenticated_client.get('/settings')
        token = get_csrf_token(settings_resp)

        # Attempt purchase
        response = authenticated_client.post('/settings/advanced/purchase', data={
            'csrf_token': token,
        }, follow_redirects=True)

        assert response.status_code == 200
        assert b'Advanced Mode purchased successfully!' in response.data

        # Verify DB state: balance deducted, purchased flag set
        user = _get_user_row(app)
        assert user['balance'] == 10000.0  # 60000 - 50000
        assert user['advanced_purchased'] == 1

    def test_purchase_insufficient_funds(self, authenticated_client, app):
        """Eligible user with insufficient balance is rejected.

        Requirements: 3.2
        """
        # Set up: user is eligible but only has $30,000
        _set_user_state(app, balance=30000.0, advanced_eligible=1)

        settings_resp = authenticated_client.get('/settings')
        token = get_csrf_token(settings_resp)

        response = authenticated_client.post('/settings/advanced/purchase', data={
            'csrf_token': token,
        }, follow_redirects=True)

        assert response.status_code == 200
        assert b'Insufficient funds' in response.data

        # Verify balance unchanged
        user = _get_user_row(app)
        assert user['balance'] == 30000.0
        assert user['advanced_purchased'] == 0

    def test_purchase_ineligible_user(self, authenticated_client, app):
        """Non-eligible user is rejected even with sufficient funds.

        Requirements: 3.3
        """
        # Set up: user has enough cash to cover the $50,000 cost but net worth
        # is below the $100,000 eligibility threshold, so auto-eligibility
        # detection won't promote them during the page render.
        _set_user_state(app, balance=60000.0, advanced_eligible=0)

        settings_resp = authenticated_client.get('/settings')
        token = get_csrf_token(settings_resp)

        response = authenticated_client.post('/settings/advanced/purchase', data={
            'csrf_token': token,
        }, follow_redirects=True)

        assert response.status_code == 200
        assert b'$100,000 net worth' in response.data

        # Verify balance unchanged
        user = _get_user_row(app)
        assert user['balance'] == 60000.0
        assert user['advanced_purchased'] == 0

    def test_purchase_double_purchase_no_op(self, authenticated_client, app):
        """Already-purchased user gets a no-op (no additional deduction).

        Requirements: 3.1, 3.4
        """
        # Set up: user already purchased, has $60,000 balance
        _set_user_state(
            app, balance=60000.0, advanced_eligible=1, advanced_purchased=1
        )

        settings_resp = authenticated_client.get('/settings')
        token = get_csrf_token(settings_resp)

        response = authenticated_client.post('/settings/advanced/purchase', data={
            'csrf_token': token,
        }, follow_redirects=True)

        assert response.status_code == 200
        assert b'already own Advanced Mode' in response.data

        # Verify balance unchanged — no double deduction
        user = _get_user_row(app)
        assert user['balance'] == 60000.0


# ---------------------------------------------------------------------------
# Toggle endpoint tests
# ---------------------------------------------------------------------------

class TestAdvancedToggle:
    """Tests for POST /settings/advanced/toggle."""

    def test_toggle_success_enable(self, authenticated_client, app):
        """Purchased user with no cooldown can toggle Advanced Mode on.

        Requirements: 4.2
        """
        # Set up: purchased, currently inactive, no recent toggle
        _set_user_state(
            app,
            advanced_eligible=1,
            advanced_purchased=1,
            advanced_active=0,
            advanced_toggled_at=None,
        )

        settings_resp = authenticated_client.get('/settings')
        token = get_csrf_token(settings_resp)

        response = authenticated_client.post('/settings/advanced/toggle', data={
            'csrf_token': token,
        }, follow_redirects=True)

        assert response.status_code == 200
        assert b'Advanced Mode enabled' in response.data

        # Verify DB state flipped
        user = _get_user_row(app)
        assert user['advanced_active'] == 1
        assert user['advanced_toggled_at'] is not None

    def test_toggle_success_disable(self, authenticated_client, app):
        """Purchased user can toggle Advanced Mode off (after cooldown expires).

        Requirements: 4.2
        """
        # Set up: purchased, currently active, toggled > 5 minutes ago
        past_time = (datetime.now() - timedelta(seconds=400)).isoformat()
        _set_user_state(
            app,
            advanced_eligible=1,
            advanced_purchased=1,
            advanced_active=1,
            advanced_toggled_at=past_time,
        )

        settings_resp = authenticated_client.get('/settings')
        token = get_csrf_token(settings_resp)

        response = authenticated_client.post('/settings/advanced/toggle', data={
            'csrf_token': token,
        }, follow_redirects=True)

        assert response.status_code == 200
        assert b'Advanced Mode disabled' in response.data

        # Verify DB state flipped
        user = _get_user_row(app)
        assert user['advanced_active'] == 0

    def test_toggle_cooldown_rejection(self, authenticated_client, app):
        """Purchased user who just toggled is rejected with cooldown message.

        Requirements: 4.3
        """
        # Set up: purchased, toggled just 30 seconds ago
        recent_time = (datetime.now() - timedelta(seconds=30)).isoformat()
        _set_user_state(
            app,
            advanced_eligible=1,
            advanced_purchased=1,
            advanced_active=1,
            advanced_toggled_at=recent_time,
        )

        settings_resp = authenticated_client.get('/settings')
        token = get_csrf_token(settings_resp)

        response = authenticated_client.post('/settings/advanced/toggle', data={
            'csrf_token': token,
        }, follow_redirects=True)

        assert response.status_code == 200
        assert b'Please wait' in response.data
        assert b'minutes' in response.data

        # Verify state unchanged
        user = _get_user_row(app)
        assert user['advanced_active'] == 1

    def test_toggle_not_purchased_rejected(self, authenticated_client, app):
        """User who hasn't purchased cannot toggle.

        Requirements: 4.2
        """
        # Set up: eligible but NOT purchased
        _set_user_state(
            app,
            advanced_eligible=1,
            advanced_purchased=0,
            advanced_active=0,
        )

        settings_resp = authenticated_client.get('/settings')
        token = get_csrf_token(settings_resp)

        response = authenticated_client.post('/settings/advanced/toggle', data={
            'csrf_token': token,
        }, follow_redirects=True)

        assert response.status_code == 200
        assert b'must purchase Advanced Mode' in response.data

        # Verify state unchanged
        user = _get_user_row(app)
        assert user['advanced_active'] == 0
