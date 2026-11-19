"""Integration tests for the Notification System lifecycle.

Tests full-page rendering, polling endpoint JSON structure, DELETE/POST
endpoints, two-panel inbox layout, account reset integration, and the
end-to-end create → poll → mark-read lifecycle.

Validates: Requirements 3.1, 6.1, 7.2, 8.1, 4.1, 10.1, 10.3
"""

import os
import re
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


@pytest.fixture(autouse=True)
def disable_bonus_reminder(monkeypatch):
    """New users always have a daily bonus waiting, so the poll would add a
    'bonus' reminder to every count in this file. These tests are about other
    notification behaviour, so switch the reminder off."""
    monkeypatch.setattr('app.routes.inbox.ensure_bonus_reminder', lambda db, user_id: None)
    yield


# ---------------------------------------------------------------------------
# Helper: get a CSRF token from any authenticated page
# ---------------------------------------------------------------------------

def _get_csrf_from_page(client):
    """Fetch the inbox page and read the CSRF token from its csrf-token meta tag
    (the page's JS sends it as X-CSRFToken)."""
    html = client.get('/inbox').data.decode('utf-8')
    match = re.search(r'<meta name="csrf-token" content="([^"]+)"', html)
    assert match, 'csrf-token meta tag missing from /inbox'
    return match.group(1)


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
        """Poll endpoint returns JSON with notifications (list) and has_unread (bool)."""
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

        response = client.get('/inbox/poll')
        assert response.status_code == 200

        data = response.get_json()
        assert 'notifications' in data
        assert 'has_unread' in data

        # Type checks
        assert isinstance(data['notifications'], list)
        assert isinstance(data['has_unread'], bool)

        # Should have 2 notifications
        assert len(data['notifications']) == 2
        assert data['has_unread'] is True

    def test_poll_only_returns_each_toast_once(self, client, app):
        """Poll returns pending toasts once; a second poll returns none (toasted flag)."""
        register_user(client, 'PollFilter', 'Password123!')

        db_path = app.config['DATABASE_PATH']
        conn = sqlite3.connect(db_path)
        row = conn.execute("SELECT id FROM users WHERE username = ?", ('PollFilter',)).fetchone()
        user_id = row[0]
        conn.close()

        with app.app_context():
            create_notification(user_id, 'system', 'First notification')
            create_notification(user_id, 'system', 'Second notification')

        # First poll returns both pending toasts
        response = client.get('/inbox/poll')
        data = response.get_json()
        assert len(data['notifications']) == 2

        # Second poll returns nothing: they've already been toasted
        response = client.get('/inbox/poll')
        data = response.get_json()
        assert len(data['notifications']) == 0
        # They're still unread, so the red dot stays on
        assert data['has_unread'] is True


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
    """Tests for the inbox page: list / select mode / full-screen detail."""

    def test_inbox_renders_list_screen(self, client, app):
        """GET /inbox opens on the list screen with the filter menu and select bar."""
        register_user(client, 'LayoutUser', 'Password123!')

        response = client.get('/inbox')
        html = response.data.decode('utf-8')

        assert response.status_code == 200
        assert 'data-view="list"' in html
        assert 'id="inbox-list"' in html
        assert 'id="inbox-filter-menu"' in html
        assert 'role="menuitemradio"' in html
        assert 'id="inbox-select-all"' in html
        assert 'id="inbox-bulk-read"' in html
        assert 'id="inbox-bulk-delete"' in html
        assert 'Tap and hold to select' in html
        # The old two-pane markup and four filter links are gone
        assert 'inbox__panels' not in html
        assert 'inbox__filter-tab' not in html
        assert 'Select a notification to view details.' not in html

    def test_rows_link_to_detail_and_have_checkboxes(self, client, app):
        register_user(client, 'RowUser', 'Password123!')
        user_id = _user_id(app, 'RowUser')
        with app.app_context():
            notif_id = create_notification(user_id, 'system', 'Row message')

        html = client.get('/inbox').data.decode('utf-8')
        assert f'href="/inbox?selected={notif_id}"' in html
        assert f'class="inbox__check-input" value="{notif_id}"' in html
        assert 'aria-label="Select notification: Row message"' in html

    def test_deep_link_opens_detail_screen_and_marks_read(self, client, app):
        """The toast/advancement link /inbox?selected=<id> lands on the detail screen."""
        register_user(client, 'DeepUser', 'Password123!')
        user_id = _user_id(app, 'DeepUser')
        with app.app_context():
            notif_id = create_notification(user_id, 'stop_loss', 'Deep linked stop loss')
            action_url = get_notifications(user_id)[0]['action_url']

        html = client.get(action_url).data.decode('utf-8')
        assert 'data-view="detail"' in html
        assert 'inbox__detail-content' in html
        assert 'Deep linked stop loss' in html
        assert re.search(r'id="inbox-detail-delete"[^>]*data-id="%d"' % notif_id, html)
        # Opening it marks it read, so the list row and the navbar dot agree
        assert 'inbox__list-item--unread' not in html
        assert 'nav__dropdown-icon--unread' not in html

    def test_unknown_selected_id_falls_back_to_list(self, client, app):
        register_user(client, 'NoSuchUser', 'Password123!')
        html = client.get('/inbox?selected=999999').data.decode('utf-8')
        assert 'data-view="list"' in html


def _user_id(app, username):
    conn = sqlite3.connect(app.config['DATABASE_PATH'])
    row = conn.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone()
    conn.close()
    return row[0]


def _read_flags(app, ids):
    conn = sqlite3.connect(app.config['DATABASE_PATH'])
    placeholders = ",".join("?" * len(ids))
    rows = conn.execute(
        f"SELECT id, is_read FROM notifications WHERE id IN ({placeholders})", ids
    ).fetchall()
    conn.close()
    return dict(rows)


class TestBulkEndpoints:
    """POST /inbox/bulk-read and /inbox/bulk-delete (select mode actions)."""

    def _setup(self, client, app, name, count=3):
        register_user(client, name, 'Password123!')
        user_id = _user_id(app, name)
        with app.app_context():
            ids = [create_notification(user_id, 'system', f'Message {i}') for i in range(count)]
        return user_id, ids, _get_csrf_from_page(client)

    def test_bulk_read_marks_only_posted_ids(self, client, app):
        _, ids, csrf = self._setup(client, app, 'BulkReadUser')
        response = client.post('/inbox/bulk-read', data={'ids': ids[:2], 'filter': 'all'},
                               headers={'X-CSRFToken': csrf})
        assert response.status_code == 200
        assert response.headers['X-Inbox-Has-Unread'] == '1'
        flags = _read_flags(app, ids)
        assert flags[ids[0]] == 1 and flags[ids[1]] == 1 and flags[ids[2]] == 0
        assert 'id="inbox-list"' in response.data.decode('utf-8')

    def test_bulk_read_all_clears_unread_header(self, client, app):
        _, ids, csrf = self._setup(client, app, 'BulkReadAll')
        response = client.post('/inbox/bulk-read', data={'ids': ids},
                               headers={'X-CSRFToken': csrf})
        assert response.headers['X-Inbox-Has-Unread'] == '0'
        assert set(_read_flags(app, ids).values()) == {1}

    def test_bulk_read_respects_filter(self, client, app):
        _, ids, csrf = self._setup(client, app, 'BulkReadFilter')
        response = client.post('/inbox/bulk-read', data={'ids': ids[:1], 'filter': 'unread'},
                               headers={'X-CSRFToken': csrf})
        html = response.data.decode('utf-8')
        assert 'data-filter="unread"' in html
        assert 'Message 0' not in html
        assert 'Message 1' in html

    def test_bulk_delete_removes_posted_ids(self, client, app):
        _, ids, csrf = self._setup(client, app, 'BulkDelUser')
        response = client.post('/inbox/bulk-delete', data={'ids': ids[:2]},
                               headers={'X-CSRFToken': csrf})
        assert response.status_code == 200
        assert list(_read_flags(app, ids)) == [ids[2]]
        html = response.data.decode('utf-8')
        assert 'Message 2' in html and 'Message 0' not in html

    def test_bulk_actions_ignore_other_users_ids(self, client, app):
        _, ids, _csrf = self._setup(client, app, 'OwnerUser', count=1)
        client.get('/logout')
        register_user(client, 'IntruderUser', 'Password123!')
        csrf = _get_csrf_from_page(client)
        client.post('/inbox/bulk-read', data={'ids': ids}, headers={'X-CSRFToken': csrf})
        client.post('/inbox/bulk-delete', data={'ids': ids}, headers={'X-CSRFToken': csrf})
        assert _read_flags(app, ids) == {ids[0]: 0}

    def test_bulk_ignores_junk_ids(self, client, app):
        _, ids, csrf = self._setup(client, app, 'JunkUser', count=1)
        response = client.post('/inbox/bulk-delete', data={'ids': ['abc', '']},
                               headers={'X-CSRFToken': csrf})
        assert response.status_code == 200
        assert _read_flags(app, ids) == {ids[0]: 0}

    def test_bulk_requires_csrf(self, client, app):
        _, ids, _csrf = self._setup(client, app, 'NoCsrfUser', count=1)
        response = client.post('/inbox/bulk-delete', data={'ids': ids})
        assert response.status_code in (400, 403)
        assert _read_flags(app, ids) == {ids[0]: 0}

    def test_single_delete_keeps_filter_and_sets_header(self, client, app):
        _, ids, csrf = self._setup(client, app, 'SingleDelUser', count=2)
        response = client.delete(f'/inbox/{ids[0]}?filter=unread', headers={'X-CSRFToken': csrf})
        assert response.status_code == 200
        assert response.headers['X-Inbox-Has-Unread'] == '1'
        html = response.data.decode('utf-8')
        assert 'data-filter="unread"' in html
        assert 'Message 1' in html and 'Message 0' not in html


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


# ---------------------------------------------------------------------------
# Daily bonus detail panel
# ---------------------------------------------------------------------------

class TestBonusDetailPanel:
    """The bonus detail panel reflects the player's bonus state *now*,
    not when the reminder was sent."""

    def _setup(self, client, app, username, cycle_day, collected_today):
        register_user(client, username, 'Password123!')
        conn = sqlite3.connect(app.config['DATABASE_PATH'])
        user_id = conn.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone()[0]
        conn.execute(
            """UPDATE users SET bonus_cycle_day = ?,
                   last_bonus_collected_date = CASE WHEN ? THEN date('now', 'localtime') ELSE NULL END
               WHERE id = ?""",
            (cycle_day, 1 if collected_today else 0, user_id),
        )
        conn.commit()
        conn.close()
        with app.app_context():
            notif_id = create_notification(
                user_id, 'bonus', 'Your daily bonus of $10,000 is ready to collect.',
                target_url='/profile',
            )
        return client.get(f'/inbox?selected={notif_id}').data.decode('utf-8')

    def test_available_bonus_shows_ready_day_and_collect_button(self, client, app):
        html = self._setup(client, app, 'BonusReady', cycle_day=2, collected_today=False)
        assert 'inbox__bonus-day--collected' in html   # day 1
        assert 'inbox__bonus-day--ready' in html       # day 2
        assert 'Day 2 of 3 is ready' in html
        assert 'Collect Bonus' in html

    def test_collected_today_shows_waiting_and_no_collect_button(self, client, app):
        # Collected day 1 today, so cycle_day is now 2 and it's waiting for midnight
        html = self._setup(client, app, 'BonusWaiting', cycle_day=2, collected_today=True)
        assert 'inbox__bonus-day--waiting' in html
        assert "Today's bonus is collected" in html
        assert 'Collect Bonus' not in html
        assert 'View Bonus' in html

    def test_complete_cycle_shows_all_collected(self, client, app):
        html = self._setup(client, app, 'BonusDone', cycle_day=4, collected_today=False)
        assert html.count('inbox__bonus-day--collected') == 3
        assert 'all three days' in html
        assert 'View Profile' in html
