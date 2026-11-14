"""Property-based tests for the Notification System creation logic.

Uses Hypothesis to verify universal correctness properties defined in the
design document for notification creation, validation, and rejection.
"""

import os
import sys
import sqlite3
from unittest.mock import patch

# Add src/ to the Python path so that `from app.models import ...` works
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'src'))

import pytest
from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st

from app.models import create_notification


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
# Feature: notification-system, Property 1: Notification creation round-trip
# Validates: Requirements 2.1, 2.2, 2.3, 2.4
# ---------------------------------------------------------------------------


@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture, HealthCheck.too_slow])
@given(
    category=st.text(min_size=1, max_size=50),
    message=st.text(min_size=1, max_size=100).filter(lambda s: s.strip()),
    action_url=st.one_of(st.none(), st.text(max_size=100)),
)
def test_notification_creation_round_trip(category, message, action_url):
    """Property 1: For any valid user, category, message, and action_url,
    create_notification returns a positive ID and the stored record matches
    all fields with is_read=0.

    **Validates: Requirements 2.1, 2.2, 2.3, 2.4**
    """
    db = _create_test_db()
    try:
        with patch('app.models.get_db', return_value=db):
            notification_id = create_notification(1, category, message, action_url)

        # Returned ID must be a positive integer
        assert isinstance(notification_id, int), (
            f"Expected int ID, got {type(notification_id).__name__}"
        )
        assert notification_id > 0, (
            f"Expected positive ID, got {notification_id}"
        )

        # Retrieve the stored record and verify all fields match
        row = db.execute(
            "SELECT * FROM notifications WHERE id = ?", (notification_id,)
        ).fetchone()
        assert row is not None, "Notification row should exist after creation"
        assert row["user_id"] == 1
        assert row["category"] == category
        assert row["message"] == message
        assert row["action_url"] == f'/inbox?selected={notification_id}'
        assert row["is_read"] == 0
        assert row["created_at"] is not None
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Feature: notification-system, Property 2: Whitespace message rejection
# Validates: Requirements 2.1, 2.2, 2.3, 2.4
# ---------------------------------------------------------------------------


@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(
    message=st.from_regex(r'^[\s]*$', fullmatch=True),
)
def test_whitespace_message_rejection(message):
    """Property 2: For any whitespace-only or empty message,
    create_notification raises ValueError and count is unchanged.

    **Validates: Requirements 2.1, 2.2, 2.3, 2.4**
    """
    db = _create_test_db()
    try:
        # Count notifications before the call
        count_before = db.execute(
            "SELECT COUNT(*) as cnt FROM notifications"
        ).fetchone()["cnt"]

        with patch('app.models.get_db', return_value=db):
            with pytest.raises(ValueError):
                create_notification(1, "test_category", message, None)

        # Count must remain unchanged
        count_after = db.execute(
            "SELECT COUNT(*) as cnt FROM notifications"
        ).fetchone()["cnt"]
        assert count_after == count_before, (
            f"Notification count changed from {count_before} to {count_after} "
            f"after rejected whitespace message"
        )
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Feature: notification-system, Property 3: Non-existent user rejection
# Validates: Requirements 2.1, 2.2, 2.3, 2.4
# ---------------------------------------------------------------------------


@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(
    user_id=st.integers(min_value=2, max_value=100000),
)
def test_non_existent_user_rejection(user_id):
    """Property 3: For any user_id not in the users table,
    create_notification raises ValueError and no row is inserted.

    **Validates: Requirements 2.1, 2.2, 2.3, 2.4**
    """
    db = _create_test_db()
    try:
        # Count notifications before the call
        count_before = db.execute(
            "SELECT COUNT(*) as cnt FROM notifications"
        ).fetchone()["cnt"]

        with patch('app.models.get_db', return_value=db):
            with pytest.raises(ValueError):
                create_notification(user_id, "achievement", "Test message", None)

        # No row should have been inserted
        count_after = db.execute(
            "SELECT COUNT(*) as cnt FROM notifications"
        ).fetchone()["cnt"]
        assert count_after == count_before, (
            f"Notification count changed from {count_before} to {count_after} "
            f"after rejected non-existent user_id={user_id}"
        )
    finally:
        db.close()
