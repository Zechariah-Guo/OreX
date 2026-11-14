"""Property-based tests for the Notification System query and mutation logic.

Uses Hypothesis to verify universal correctness properties defined in the
design document for notification querying, marking read, deleting, and polling.
"""

import os
import sys
import sqlite3
from unittest.mock import patch

# Add src/ to the Python path so that `from app.models import ...` works
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'src'))

import pytest
from hypothesis import given, settings, HealthCheck, assume
from hypothesis import strategies as st

from app.models import (
    create_notification,
    get_notifications,
    get_notification_detail,
    has_unread_notifications,
    get_new_notifications_since,
    mark_notification_read,
    mark_all_notifications_read,
    delete_notification,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _create_test_db():
    """Create an in-memory SQLite database with the required schema for testing."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")

    # Create users table
    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY,
            username TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            balance REAL NOT NULL DEFAULT 10000,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            last_login TEXT,
            totp_enabled INTEGER NOT NULL DEFAULT 0,
            totp_secret_encrypted TEXT,
            advanced_eligible INTEGER NOT NULL DEFAULT 0,
            advanced_purchased INTEGER NOT NULL DEFAULT 0,
            advanced_active INTEGER NOT NULL DEFAULT 0,
            advanced_toggled_at TEXT DEFAULT NULL,
            play_time INTEGER NOT NULL DEFAULT 0,
            login_streak INTEGER NOT NULL DEFAULT 0,
            last_streak_date TEXT DEFAULT NULL,
            money_theme_unlocked INTEGER NOT NULL DEFAULT 0,
            gold_theme_unlocked INTEGER NOT NULL DEFAULT 0
        )
    """)

    # Create notifications table
    conn.execute("""
        CREATE TABLE IF NOT EXISTS notifications (
            id INTEGER PRIMARY KEY,
            user_id INTEGER NOT NULL,
            category TEXT NOT NULL,
            message TEXT NOT NULL,
            action_url TEXT DEFAULT NULL,
            target_url TEXT DEFAULT NULL,
            is_read INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        )
    """)

    # Create indexes
    conn.execute("CREATE INDEX IF NOT EXISTS idx_notifications_user_read ON notifications(user_id, is_read)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_notifications_user_id_desc ON notifications(user_id, id DESC)")

    # Insert a test user
    conn.execute(
        "INSERT INTO users (id, username, password_hash) VALUES (1, 'testuser', 'hash123')"
    )
    conn.commit()
    return conn


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

CATEGORIES = st.sampled_from(["achievement", "liquidation", "trade", "system", "alert"])
MESSAGES = st.text(min_size=1, max_size=80).filter(lambda s: s.strip())


# ---------------------------------------------------------------------------
# Feature: notification-system, Property 4: Has-unread accuracy
# Validates: Requirements 3.2, 4.1
# ---------------------------------------------------------------------------


@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture, HealthCheck.too_slow])
@given(
    num_notifications=st.integers(min_value=0, max_value=10),
    categories=st.lists(CATEGORIES, min_size=10, max_size=10),
    messages=st.lists(MESSAGES, min_size=10, max_size=10),
    read_flags=st.lists(st.booleans(), min_size=10, max_size=10),
)
def test_has_unread_accuracy(num_notifications, categories, messages, read_flags):
    """Property 4: For any user with at least one is_read=0 notification,
    has_unread returns True; with all read or none, returns False.

    **Validates: Requirements 3.2, 4.1**
    """
    db = _create_test_db()
    try:
        with patch('app.models.get_db', return_value=db):
            # Create notifications up to num_notifications
            notification_ids = []
            for i in range(num_notifications):
                nid = create_notification(1, categories[i], messages[i])
                notification_ids.append(nid)

            # Mark some as read based on read_flags
            for i, nid in enumerate(notification_ids):
                if read_flags[i]:
                    db.execute(
                        "UPDATE notifications SET is_read = 1 WHERE id = ?", (nid,)
                    )
            db.commit()

            # Determine expected result
            has_any_unread = any(not read_flags[i] for i in range(num_notifications))

            result = has_unread_notifications(1)

        if num_notifications == 0:
            assert result is False, "No notifications should mean has_unread is False"
        elif has_any_unread:
            assert result is True, (
                f"Expected has_unread=True with {num_notifications} notifications "
                f"and read_flags={read_flags[:num_notifications]}"
            )
        else:
            assert result is False, (
                f"Expected has_unread=False with all notifications read"
            )
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Feature: notification-system, Property 5: List ordering is newest-first
# Validates: Requirements 4.1
# ---------------------------------------------------------------------------


@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture, HealthCheck.too_slow])
@given(
    num_notifications=st.integers(min_value=2, max_value=15),
    categories=st.lists(CATEGORIES, min_size=15, max_size=15),
    messages=st.lists(MESSAGES, min_size=15, max_size=15),
)
def test_list_ordering_newest_first(num_notifications, categories, messages):
    """Property 5: For any user with multiple notifications,
    get_notifications returns them in strictly descending id order.

    **Validates: Requirements 4.1**
    """
    db = _create_test_db()
    try:
        with patch('app.models.get_db', return_value=db):
            # Create multiple notifications
            for i in range(num_notifications):
                create_notification(1, categories[i], messages[i])

            # Retrieve and check ordering
            results = get_notifications(1)

        assert len(results) == num_notifications, (
            f"Expected {num_notifications} notifications, got {len(results)}"
        )

        # Verify strictly descending IDs
        ids = [row['id'] for row in results]
        for i in range(len(ids) - 1):
            assert ids[i] > ids[i + 1], (
                f"Notifications not in descending id order: {ids}"
            )
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Feature: notification-system, Property 6: Mark-all-read marks all
# Validates: Requirements 4.5, 7.1
# ---------------------------------------------------------------------------


@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture, HealthCheck.too_slow])
@given(
    num_notifications=st.integers(min_value=1, max_value=10),
    categories=st.lists(CATEGORIES, min_size=10, max_size=10),
    messages=st.lists(MESSAGES, min_size=10, max_size=10),
    read_flags=st.lists(st.booleans(), min_size=10, max_size=10),
)
def test_mark_all_read_marks_all(num_notifications, categories, messages, read_flags):
    """Property 6: For any user with unread notifications,
    mark_all_notifications_read results in has_unread returning False.

    **Validates: Requirements 4.5, 7.1**
    """
    db = _create_test_db()
    try:
        with patch('app.models.get_db', return_value=db):
            # Create notifications
            notification_ids = []
            for i in range(num_notifications):
                nid = create_notification(1, categories[i], messages[i])
                notification_ids.append(nid)

            # Mark some as already read (to create a mixed state)
            for i, nid in enumerate(notification_ids):
                if read_flags[i]:
                    db.execute(
                        "UPDATE notifications SET is_read = 1 WHERE id = ?", (nid,)
                    )
            db.commit()

            # Ensure at least one is unread before marking all
            has_any_unread = any(not read_flags[i] for i in range(num_notifications))
            assume(has_any_unread)

            # Mark all as read
            mark_all_notifications_read(1)

            # has_unread should now be False
            result = has_unread_notifications(1)

        assert result is False, (
            f"Expected has_unread=False after mark_all_notifications_read, "
            f"but got True"
        )
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Feature: notification-system, Property 8: Watermark filtering returns only newer unread
# Validates: Requirements 6.5
# ---------------------------------------------------------------------------


@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture, HealthCheck.too_slow])
@given(
    num_notifications=st.integers(min_value=2, max_value=10),
    categories=st.lists(CATEGORIES, min_size=10, max_size=10),
    messages=st.lists(MESSAGES, min_size=10, max_size=10),
    read_flags=st.lists(st.booleans(), min_size=10, max_size=10),
    watermark_index=st.integers(min_value=0, max_value=9),
)
def test_watermark_filtering_returns_only_newer_unread(
    num_notifications, categories, messages, read_flags, watermark_index
):
    """Property 8: For any since_id, get_new_notifications_since returns only
    unread notifications with id > since_id.

    **Validates: Requirements 6.5**
    """
    # Ensure watermark_index is within our notification count
    assume(watermark_index < num_notifications)

    db = _create_test_db()
    try:
        with patch('app.models.get_db', return_value=db):
            # Create notifications
            notification_ids = []
            for i in range(num_notifications):
                nid = create_notification(1, categories[i], messages[i])
                notification_ids.append(nid)

            # Mark some as read
            for i, nid in enumerate(notification_ids):
                if read_flags[i]:
                    db.execute(
                        "UPDATE notifications SET is_read = 1 WHERE id = ?", (nid,)
                    )
            db.commit()

            # Use the notification at watermark_index as the since_id
            since_id = notification_ids[watermark_index]

            # Get new notifications since the watermark
            results = get_new_notifications_since(1, since_id)

        # Verify all returned notifications have id > since_id and are unread
        for row in results:
            assert row['id'] > since_id, (
                f"Returned notification id={row['id']} is not > since_id={since_id}"
            )
            assert row['is_read'] == 0, (
                f"Returned notification id={row['id']} has is_read={row['is_read']}, "
                f"expected 0 (unread)"
            )

        # Verify completeness: all unread notifications with id > since_id are returned
        result_ids = {row['id'] for row in results}
        for i, nid in enumerate(notification_ids):
            if nid > since_id and not read_flags[i]:
                assert nid in result_ids, (
                    f"Expected unread notification id={nid} (> since_id={since_id}) "
                    f"to be in results but it was missing"
                )
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Feature: notification-system, Property 9: Single delete removes exactly one
# Validates: Requirements 8.1, 8.3
# ---------------------------------------------------------------------------


@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture, HealthCheck.too_slow])
@given(
    num_notifications=st.integers(min_value=2, max_value=10),
    categories=st.lists(CATEGORIES, min_size=10, max_size=10),
    messages=st.lists(MESSAGES, min_size=10, max_size=10),
    delete_index=st.integers(min_value=0, max_value=9),
)
def test_single_delete_removes_exactly_one(num_notifications, categories, messages, delete_index):
    """Property 9: delete_notification removes the target and leaves all others
    unchanged.

    **Validates: Requirements 8.1, 8.3**
    """
    assume(delete_index < num_notifications)

    db = _create_test_db()
    try:
        with patch('app.models.get_db', return_value=db):
            # Create notifications
            notification_ids = []
            for i in range(num_notifications):
                nid = create_notification(1, categories[i], messages[i])
                notification_ids.append(nid)

            target_id = notification_ids[delete_index]

            # Delete the target notification
            success = delete_notification(target_id, 1)

        assert success is True, f"delete_notification should return True for existing notification"

        # Verify target is gone
        row = db.execute(
            "SELECT * FROM notifications WHERE id = ?", (target_id,)
        ).fetchone()
        assert row is None, f"Deleted notification id={target_id} should not exist"

        # Verify all other notifications still exist
        remaining_ids = [nid for nid in notification_ids if nid != target_id]
        for nid in remaining_ids:
            row = db.execute(
                "SELECT * FROM notifications WHERE id = ?", (nid,)
            ).fetchone()
            assert row is not None, (
                f"Notification id={nid} should still exist after deleting id={target_id}"
            )

        # Verify total count is reduced by exactly one
        count = db.execute(
            "SELECT COUNT(*) as cnt FROM notifications WHERE user_id = 1"
        ).fetchone()["cnt"]
        assert count == num_notifications - 1, (
            f"Expected {num_notifications - 1} notifications after delete, got {count}"
        )
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Feature: notification-system, Property 10: Mark-read sets is_read without deleting
# Validates: Requirements 7.1
# ---------------------------------------------------------------------------


@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture, HealthCheck.too_slow])
@given(
    num_notifications=st.integers(min_value=1, max_value=10),
    categories=st.lists(CATEGORIES, min_size=10, max_size=10),
    messages=st.lists(MESSAGES, min_size=10, max_size=10),
    mark_index=st.integers(min_value=0, max_value=9),
)
def test_mark_read_sets_is_read_without_deleting(num_notifications, categories, messages, mark_index):
    """Property 10: mark_notification_read sets is_read=1 and the notification
    remains retrievable.

    **Validates: Requirements 7.1**
    """
    assume(mark_index < num_notifications)

    db = _create_test_db()
    try:
        with patch('app.models.get_db', return_value=db):
            # Create notifications
            notification_ids = []
            for i in range(num_notifications):
                nid = create_notification(1, categories[i], messages[i])
                notification_ids.append(nid)

            target_id = notification_ids[mark_index]

            # Mark the target as read
            success = mark_notification_read(target_id, 1)

        assert success is True, f"mark_notification_read should return True for existing notification"

        # Verify is_read is now 1
        row = db.execute(
            "SELECT * FROM notifications WHERE id = ?", (target_id,)
        ).fetchone()
        assert row is not None, (
            f"Notification id={target_id} should still exist after mark_read"
        )
        assert row['is_read'] == 1, (
            f"Expected is_read=1 after mark_notification_read, got {row['is_read']}"
        )

        # Verify it's still retrievable via get_notification_detail
        with patch('app.models.get_db', return_value=db):
            detail = get_notification_detail(target_id, 1)
        assert detail is not None, (
            f"Notification id={target_id} should be retrievable via get_notification_detail "
            f"after marking as read"
        )
        assert detail['is_read'] == 1

        # Verify total notification count is unchanged
        count = db.execute(
            "SELECT COUNT(*) as cnt FROM notifications WHERE user_id = 1"
        ).fetchone()["cnt"]
        assert count == num_notifications, (
            f"Expected {num_notifications} notifications (no deletion), got {count}"
        )
    finally:
        db.close()
