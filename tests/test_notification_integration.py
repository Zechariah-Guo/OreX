"""Integration tests for the Notification System lifecycle.

Tests full-page rendering, polling endpoint JSON structure, DELETE/POST
endpoints, two-panel inbox layout, account reset integration, and the
end-to-end create → poll → mark-read lifecycle.

Validates: Requirements 3.1, 6.1, 7.2, 8.1, 4.1, 10.1, 10.3
"""

import os
import sys
import sqlite3

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'src'))

import pytest

from app.models import create_notification, reset_account, has_unread_notifications, get_notifications
from conftest import register_user, login_user, get_csrf_token


# ---------------------------------------------------------------------------
# Fixture: clear notifications table before each test
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def clear_notifications(app):
    """Clear the notifications table before each test."""
    db_path = app.config['DATABASE_PATH']
    conn = sqlite3.connect(db_path)
    conn.execute("DELETE FROM notifications")
    conn.commit()
    conn.close()
    yield


# ---------------------------------------------------------------------------
# Helper: get a CSRF token from any authenticated page
# ---------------------------------------------------------------------------

def _get_csrf_from_page(client):
    """Fetch the inbox page and extract a CSRF token from hidden input."""
    resp = client.get('/inbox')
    return get_csrf_token(resp)


# ---------------------------------------------------------------------------
# 1. TestProfileDropdownInboxIcon
# ---------------------------------------------------------------------------

class TestProfileDropdownInboxIcon:
    """Test that authenticated pages include the inbox icon in the profile dropdown."""

    def test_authenticated_page_has_inbox_icon(self, client, app):
        """Any authenticated page should include the nav dropdown inbox icon
        with the correct aria-label."""
        register_user(client, 'IconUser', 'Password123!')

        response = client.get('/inbox')
        html = response.data.decode('utf-8')

        # The inbox icon link should be present with the nav__dropdown-icon class
        assert 'nav__dropdown-icon' in html
        # Should have aria-label containing "Inbox"
        assert 'aria-label="Inbox"' in html or 'aria-label="Inbox - unread notifications"' in html


# ---------------------------------------------------------------------------
# 2. TestPollingEndpoint
# ---------------------------------------------------------------------------

class TestPollingEndpoint:
    """Tests for the GET /inbox/poll endpoint JSON structure."""

    def test_poll_returns_correct_json_structure(self, client, app):
        """Poll endpoint returns JSON with notifications (list), has_unread (bool),
        and last_id (int)."""
        register_user(client, 'PollUser', 'Password123!')

        # Get user_id
        db_path = app.config['DATABASE_PATH']
        conn = sqlite3.connect(db_path)
        row = conn.execute("SELECT id FROM users WHERE username = ?", ('PollUser',)).fetchone()
        user_id = row[0]
        conn.close()

        # Create some notifications
        with app.app_context():
            create_notification(user_id, 'achievement', 'Badge earned!')
            create_notification(user_id, 'system', 'Welcome!')

        response = client.get('/inbox/poll?since=0')
        assert response.status_code == 200

        data = response.get_json()
        assert 'notifications' in data
        assert 'has_unread' in data
        assert 'last_id' in data

        # Type checks
        assert isinstance(data['notifications'], list)
        assert isinstance(data['has_unread'], bool)
        assert isinstance(data['last_id'], int)

        # Should have 2 notifications
        assert len(data['notifications']) == 2
        assert data['has_unread'] is True

    def test_poll_since_filters_correctly(self, client, app):
        """Poll with since=0 returns all unread; poll with since=last_id returns empty."""
        register_user(client, 'PollFilter', 'Password123!')

        db_path = app.config['DATABASE_PATH']
        conn = sqlite3.connect(db_path)
        row = conn.execute("SELECT id FROM users WHERE username = ?", ('PollFilter',)).fetchone()
        user_id = row[0]
        conn.close()

        with app.app_context():
            create_notification(user_id, 'system', 'First notification')
            create_notification(user_id, 'system', 'Second notification')

        # Poll with since=0 should return all
        response = client.get('/inbox/poll?since=0')
        data = response.get_json()
        assert len(data['notifications']) == 2

        last_id = data['last_id']

        # Poll with since=last_id should return empty (no newer notifications)
        response = client.get(f'/inbox/poll?since={last_id}')
        data = response.get_json()
        assert len(data['notifications']) == 0


# ---------------------------------------------------------------------------
# 3. TestDeleteEndpoint
# ---------------------------------------------------------------------------

class TestDeleteEndpoint:
    """Tests for the DELETE /inbox/<id> endpoint."""

    def test_delete_removes_notification_returns_list_partial(self, client, app):
        """DELETE request removes notification from DB and returns 200 with
        the updated list partial HTML."""
        register_user(client, 'DeleteUser', 'Password123!')

        db_path = app.config['DATABASE_PATH']
        conn = sqlite3.connect(db_path)
        row = conn.execute("SELECT id FROM users WHERE username = ?", ('DeleteUser',)).fetchone()
        user_id = row[0]
        conn.close()

        with app.app_context():
            notif_id = create_notification(user_id, 'system', 'To be deleted')

        # Get CSRF token from a page
        csrf_token = _get_csrf_from_page(client)

        # Send DELETE request with CSRF token in header
        response = client.delete(
            f'/inbox/{notif_id}',
            headers={'X-CSRFToken': csrf_token},
        )

        assert response.status_code == 200

        # Verify notification is gone from the DB
        conn = sqlite3.connect(db_path)
        count = conn.execute(
            "SELECT COUNT(*) FROM notifications WHERE id = ?", (notif_id,)
        ).fetchone()[0]
        conn.close()

        assert count == 0


# ---------------------------------------------------------------------------
# 4. TestMarkReadEndpoint
# ---------------------------------------------------------------------------

class TestMarkReadEndpoint:
    """Tests for the POST /inbox/<id>/read endpoint."""

    def test_mark_read_sets_is_read_and_returns_detail(self, client, app):
        """POST /inbox/<id>/read sets is_read=1 in DB and returns detail partial HTML."""
        register_user(client, 'ReadUser', 'Password123!')

        db_path = app.config['DATABASE_PATH']
        conn = sqlite3.connect(db_path)
        row = conn.execute("SELECT id FROM users WHERE username = ?", ('ReadUser',)).fetchone()
        user_id = row[0]
        conn.close()

        with app.app_context():
            notif_id = create_notification(user_id, 'achievement', 'You did it!')

        # Get CSRF token
        csrf_token = _get_csrf_from_page(client)

        # POST to mark as read
        response = client.post(
            f'/inbox/{notif_id}/read',
            data={'csrf_token': csrf_token},
        )

        assert response.status_code == 200

        # Verify is_read=1 in DB
        conn = sqlite3.connect(db_path)
        is_read = conn.execute(
            "SELECT is_read FROM notifications WHERE id = ?", (notif_id,)
        ).fetchone()[0]
        conn.close()

        assert is_read == 1

        # Response should contain detail partial HTML content
        html = response.data.decode('utf-8')
        assert 'inbox__detail-content' in html


# ---------------------------------------------------------------------------
# 5. TestInboxPageLayout
# ---------------------------------------------------------------------------

class TestInboxPageLayout:
    """Tests for the inbox page two-panel layout."""

    def test_inbox_renders_two_panel_layout(self, client, app):
        """GET /inbox renders the inbox page with inbox__list and inbox__detail sections."""
        register_user(client, 'LayoutUser', 'Password123!')

        response = client.get('/inbox')
        html = response.data.decode('utf-8')

        assert response.status_code == 200
        assert 'inbox__list' in html
        assert 'inbox__detail' in html
        assert 'inbox__panels' in html


# ---------------------------------------------------------------------------
# 6. TestAccountResetIntegration
# ---------------------------------------------------------------------------

class TestAccountResetIntegration:
    """Tests for account reset clearing notifications."""

    def test_reset_then_inbox_shows_empty_state(self, client, app):
        """After reset_account, the inbox page should show the empty state."""
        register_user(client, 'ResetUser', 'Password123!')

        db_path = app.config['DATABASE_PATH']
        conn = sqlite3.connect(db_path)
        row = conn.execute("SELECT id FROM users WHERE username = ?", ('ResetUser',)).fetchone()
        user_id = row[0]
        conn.close()

        # Create notifications
        with app.app_context():
            create_notification(user_id, 'achievement', 'Badge unlocked!')
            create_notification(user_id, 'system', 'Welcome!')

        # Verify notifications exist
        with app.app_context():
            notifs = get_notifications(user_id)
            assert len(notifs) == 2

        # Reset account
        with app.app_context():
            reset_account(user_id)

        # Visit inbox — should show empty state
        response = client.get('/inbox')
        html = response.data.decode('utf-8')

        assert 'inbox__empty-state' in html
        assert 'No notifications to show.' in html


# ---------------------------------------------------------------------------
# 7. TestNotificationLifecycle
# ---------------------------------------------------------------------------

class TestNotificationLifecycle:
    """Tests for the full notification lifecycle: create → poll → mark read."""

    def test_create_poll_mark_read_lifecycle(self, client, app):
        """create_notification → poll (verify present) → mark as read →
        verify is_read=1 → poll returns has_unread=False."""
        register_user(client, 'LifecycleUser', 'Password123!')

        db_path = app.config['DATABASE_PATH']
        conn = sqlite3.connect(db_path)
        row = conn.execute("SELECT id FROM users WHERE username = ?", ('LifecycleUser',)).fetchone()
        user_id = row[0]
        conn.close()

        # Step 1: Create a notification
        with app.app_context():
            notif_id = create_notification(user_id, 'liquidation', 'Position liquidated!')

        # Step 2: Poll — notification should appear
        response = client.get('/inbox/poll?since=0')
        data = response.get_json()
        assert len(data['notifications']) == 1
        assert data['notifications'][0]['id'] == notif_id
        assert data['has_unread'] is True

        # Step 3: Mark as read
        csrf_token = _get_csrf_from_page(client)
        response = client.post(
            f'/inbox/{notif_id}/read',
            data={'csrf_token': csrf_token},
        )
        assert response.status_code == 200

        # Step 4: Verify is_read=1 in DB
        conn = sqlite3.connect(db_path)
        is_read = conn.execute(
            "SELECT is_read FROM notifications WHERE id = ?", (notif_id,)
        ).fetchone()[0]
        conn.close()
        assert is_read == 1

        # Step 5: Poll again — has_unread should be False
        response = client.get(f'/inbox/poll?since=0')
        data = response.get_json()
        assert data['has_unread'] is False


# ---------------------------------------------------------------------------
# 8. TestSLTPToastPolling
# ---------------------------------------------------------------------------

class TestSLTPToastPolling:
    """Tests verifying SL/TP notifications appear in poll with correct category styling.

    Validates: Requirements 6.1, 6.2
    """

    def test_stop_loss_notification_appears_in_poll_with_correct_style(self, client, app):
        """A stop_loss notification should appear in poll response with
        css_class='flash--stop-loss', duration=3000, and has_unread=True."""
        register_user(client, 'SLPollUser', 'Password123!')

        db_path = app.config['DATABASE_PATH']
        conn = sqlite3.connect(db_path)
        row = conn.execute("SELECT id FROM users WHERE username = ?", ('SLPollUser',)).fetchone()
        user_id = row[0]
        conn.close()

        with app.app_context():
            create_notification(user_id, 'stop_loss', 'Stop Loss triggered: sold 10 Emerald at $45.00')

        response = client.get('/inbox/poll?since=0')
        assert response.status_code == 200

        data = response.get_json()
        assert data['has_unread'] is True
        assert len(data['notifications']) == 1

        notif = data['notifications'][0]
        assert notif['category'] == 'stop_loss'
        assert notif['css_class'] == 'flash--stop-loss'
        assert notif['duration'] == 3000
        assert 'Stop Loss triggered' in notif['message']

    def test_take_profit_notification_appears_in_poll_with_correct_style(self, client, app):
        """A take_profit notification should appear in poll response with
        css_class='flash--take-profit', duration=3000, and has_unread=True."""
        register_user(client, 'TPPollUser', 'Password123!')

        db_path = app.config['DATABASE_PATH']
        conn = sqlite3.connect(db_path)
        row = conn.execute("SELECT id FROM users WHERE username = ?", ('TPPollUser',)).fetchone()
        user_id = row[0]
        conn.close()

        with app.app_context():
            create_notification(user_id, 'take_profit', 'Take Profit triggered: sold 5 Diamond at $120.00')

        response = client.get('/inbox/poll?since=0')
        assert response.status_code == 200

        data = response.get_json()
        assert data['has_unread'] is True
        assert len(data['notifications']) == 1

        notif = data['notifications'][0]
        assert notif['category'] == 'take_profit'
        assert notif['css_class'] == 'flash--take-profit'
        assert notif['duration'] == 3000
        assert 'Take Profit triggered' in notif['message']

    def test_sltp_notification_action_url_points_to_inbox(self, client, app):
        """A stop_loss notification's action_url should point to /inbox?selected=<id>."""
        register_user(client, 'SLUrlUser', 'Password123!')

        db_path = app.config['DATABASE_PATH']
        conn = sqlite3.connect(db_path)
        row = conn.execute("SELECT id FROM users WHERE username = ?", ('SLUrlUser',)).fetchone()
        user_id = row[0]
        conn.close()

        with app.app_context():
            create_notification(user_id, 'stop_loss', 'Stop Loss triggered: sold 3 Gold at $80.00')

        response = client.get('/inbox/poll?since=0')
        assert response.status_code == 200

        data = response.get_json()
        assert len(data['notifications']) == 1

        notif = data['notifications'][0]
        assert notif['action_url'] is not None
        assert notif['action_url'].startswith('/inbox?selected=')
