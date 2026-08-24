"""Unit tests for the Notification System.

Example-based tests covering template rendering (red dot, inbox list styling),
model functions (category styles), endpoint auth, filter behavior, and CASCADE
delete behavior.

Validates: Requirements 3.3, 3.5, 8.2, 9.1, 9.2, 6.4, 11.1, 10.2
"""

import os
import sys
import sqlite3

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'src'))

import pytest

from app.models import create_notification, get_notification_style
from conftest import register_user, login_user, get_csrf_token


# ---------------------------------------------------------------------------
# Fixture: clear notifications table before each test
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def clear_notifications(app):
    """Clear the notifications table before each test.

    The db_reset fixture doesn't drop the notifications table, so we need
    to clear it manually to avoid cross-test contamination.
    """
    db_path = app.config['DATABASE_PATH']
    conn = sqlite3.connect(db_path)
    conn.execute("DELETE FROM notifications")
    conn.commit()
    conn.close()
    yield


# ---------------------------------------------------------------------------
# Fixture: authenticated client with notifications
# ---------------------------------------------------------------------------

@pytest.fixture()
def auth_client_with_notifications(client, app):
    """Register a user, create notifications, and yield authenticated client."""
    register_user(client, 'NotifUser', 'Password123!')

    # Get the user's ID from the database
    db_path = app.config['DATABASE_PATH']
    conn = sqlite3.connect(db_path)
    row = conn.execute("SELECT id FROM users WHERE username = ?", ('NotifUser',)).fetchone()
    user_id = row[0]
    conn.close()

    # Create notifications within app context (needed for get_db())
    with app.app_context():
        create_notification(user_id, 'achievement', 'You earned a badge!')
        create_notification(user_id, 'liquidation', 'Position liquidated')
        create_notification(user_id, 'system', 'Welcome to OreX')

    yield client, user_id


# ---------------------------------------------------------------------------
# 1. Red dot appears when has_unread is True
# ---------------------------------------------------------------------------

class TestRedDotIndicator:
    """Tests for the unread notification red dot in the nav dropdown."""

    def test_red_dot_appears_when_has_unread(self, auth_client_with_notifications):
        """Nav dropdown inbox icon has 'nav__dropdown-icon--unread' class when
        user has unread notifications."""
        client, _ = auth_client_with_notifications

        # Visit any authenticated page that renders the nav
        response = client.get('/inbox')
        html = response.data.decode('utf-8')

        assert 'nav__dropdown-icon--unread' in html
        assert 'Inbox - unread notifications' in html

    def test_red_dot_hidden_when_no_unread(self, client, app):
        """Nav dropdown inbox icon does NOT have 'nav__dropdown-icon--unread'
        class when user has no unread notifications."""
        register_user(client, 'NoNotifUser', 'Password123!')

        # User has no notifications at all, so no unread
        response = client.get('/inbox')
        html = response.data.decode('utf-8')

        assert 'nav__dropdown-icon--unread' not in html
        # Should have the plain aria-label without "unread notifications"
        assert 'aria-label="Inbox"' in html


# ---------------------------------------------------------------------------
# 3. Inbox list shows bold for unread entries
# ---------------------------------------------------------------------------

class TestInboxListStyling:
    """Tests for inbox list item read/unread CSS classes."""

    def test_unread_entries_have_unread_class(self, auth_client_with_notifications):
        """Unread notifications in the inbox list have 'inbox__list-item--unread' class."""
        client, _ = auth_client_with_notifications

        response = client.get('/inbox')
        html = response.data.decode('utf-8')

        assert 'inbox__list-item--unread' in html

    def test_read_entries_have_read_class(self, auth_client_with_notifications, app):
        """Read notifications in the inbox list have 'inbox__list-item--read' class."""
        client, user_id = auth_client_with_notifications

        # Mark one notification as read directly in DB
        db_path = app.config['DATABASE_PATH']
        conn = sqlite3.connect(db_path)
        conn.execute(
            "UPDATE notifications SET is_read = 1 WHERE user_id = ? AND category = ?",
            (user_id, 'achievement'),
        )
        conn.commit()
        conn.close()

        response = client.get('/inbox')
        html = response.data.decode('utf-8')

        # Should have both read and unread items
        assert 'inbox__list-item--read' in html
        assert 'inbox__list-item--unread' in html


# ---------------------------------------------------------------------------
# 5. Achievement category returns yellow class
# 6. Liquidation category returns red class
# ---------------------------------------------------------------------------

class TestCategoryStyles:
    """Tests for get_notification_style category mapping."""

    def test_achievement_returns_flash_achievement(self):
        """Achievement category returns 'flash--achievement' CSS class."""
        css_class, icon, duration = get_notification_style('achievement')

        assert css_class == 'flash--achievement'
        assert duration == 5000

    def test_liquidation_returns_flash_liquidation(self):
        """Liquidation category returns 'flash--liquidation' CSS class."""
        css_class, icon, duration = get_notification_style('liquidation')

        assert css_class == 'flash--liquidation'
        assert duration == 5000

    def test_unknown_category_returns_default(self):
        """Unknown category returns 'flash--default' CSS class with 3000ms duration."""
        css_class, icon, duration = get_notification_style('something_else')

        assert css_class == 'flash--default'
        assert duration == 3000


# ---------------------------------------------------------------------------
# 7. Poll endpoint returns 401 for unauthenticated users
# ---------------------------------------------------------------------------

class TestPollAuth:
    """Tests for poll endpoint authentication requirement."""

    def test_poll_returns_redirect_for_unauthenticated(self, client):
        """GET /inbox/poll without authentication redirects to login (302)."""
        response = client.get('/inbox/poll')

        # Flask-Login redirects unauthenticated users to login page
        assert response.status_code == 302
        assert '/login' in response.headers['Location']


# ---------------------------------------------------------------------------
# 8. Filter tabs correctly filter notifications
# ---------------------------------------------------------------------------

class TestFilterTabs:
    """Tests for inbox filter functionality."""

    def test_filter_unread_returns_only_unread(self, auth_client_with_notifications, app):
        """Filter='unread' shows only unread notifications."""
        client, user_id = auth_client_with_notifications

        # Mark one notification as read
        db_path = app.config['DATABASE_PATH']
        conn = sqlite3.connect(db_path)
        conn.execute(
            "UPDATE notifications SET is_read = 1 WHERE user_id = ? AND category = ?",
            (user_id, 'achievement'),
        )
        conn.commit()
        conn.close()

        response = client.get('/inbox?filter=unread')
        html = response.data.decode('utf-8')

        # Should have unread items but no read items in the list
        assert 'inbox__list-item--unread' in html
        assert 'inbox__list-item--read' not in html

    def test_filter_read_returns_only_read(self, auth_client_with_notifications, app):
        """Filter='read' shows only read notifications."""
        client, user_id = auth_client_with_notifications

        # Mark one notification as read
        db_path = app.config['DATABASE_PATH']
        conn = sqlite3.connect(db_path)
        conn.execute(
            "UPDATE notifications SET is_read = 1 WHERE user_id = ? AND category = ?",
            (user_id, 'achievement'),
        )
        conn.commit()
        conn.close()

        response = client.get('/inbox?filter=read')
        html = response.data.decode('utf-8')

        # Should have read items but no unread items
        assert 'inbox__list-item--read' in html
        assert 'inbox__list-item--unread' not in html

    def test_filter_all_returns_both(self, auth_client_with_notifications, app):
        """Filter='all' shows both read and unread notifications."""
        client, user_id = auth_client_with_notifications

        # Mark one notification as read
        db_path = app.config['DATABASE_PATH']
        conn = sqlite3.connect(db_path)
        conn.execute(
            "UPDATE notifications SET is_read = 1 WHERE user_id = ? AND category = ?",
            (user_id, 'achievement'),
        )
        conn.commit()
        conn.close()

        response = client.get('/inbox?filter=all')
        html = response.data.decode('utf-8')

        # Should have both
        assert 'inbox__list-item--read' in html
        assert 'inbox__list-item--unread' in html


# ---------------------------------------------------------------------------
# 9. CASCADE delete removes notifications when user is deleted
# ---------------------------------------------------------------------------

class TestCascadeDelete:
    """Tests for CASCADE delete behavior on user deletion."""

    def test_cascade_delete_removes_notifications(self, client, app):
        """Deleting a user removes all their notifications via CASCADE FK."""
        register_user(client, 'CascadeUser', 'Password123!')

        db_path = app.config['DATABASE_PATH']
        conn = sqlite3.connect(db_path)
        conn.execute("PRAGMA foreign_keys = ON")

        # Get user ID
        row = conn.execute("SELECT id FROM users WHERE username = ?", ('CascadeUser',)).fetchone()
        user_id = row[0]

        # Insert notifications directly
        conn.execute(
            "INSERT INTO notifications (user_id, category, message, is_read, created_at) "
            "VALUES (?, 'test', 'msg1', 0, datetime('now'))",
            (user_id,),
        )
        conn.execute(
            "INSERT INTO notifications (user_id, category, message, is_read, created_at) "
            "VALUES (?, 'test', 'msg2', 0, datetime('now'))",
            (user_id,),
        )
        conn.commit()

        # Verify notifications exist
        count = conn.execute(
            "SELECT COUNT(*) FROM notifications WHERE user_id = ?", (user_id,)
        ).fetchone()[0]
        assert count == 2

        # Delete the user (CASCADE should remove notifications)
        conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
        conn.commit()

        # Verify notifications are gone
        count = conn.execute(
            "SELECT COUNT(*) FROM notifications WHERE user_id = ?", (user_id,)
        ).fetchone()[0]
        assert count == 0

        conn.close()
