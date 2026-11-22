"""Property-based tests for the Notification System account reset logic.

Uses Hypothesis to verify that account reset removes all notifications
for the target user without affecting other users' notifications.
"""

import os
import sys
import sqlite3
from unittest.mock import patch, MagicMock

# Add src/ to the Python path so that `from app.models import ...` works
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'src'))

import pytest
from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st

from app.models import reset_account


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
            gold_theme_unlocked INTEGER NOT NULL DEFAULT 0,
            avatar_path TEXT DEFAULT NULL,
            avatar_color TEXT DEFAULT NULL,
            peak_net_worth REAL NOT NULL DEFAULT 10000,
            bonus_cycle_day INTEGER NOT NULL DEFAULT 1,
            last_bonus_collected_date TEXT DEFAULT NULL,
            session_version INTEGER NOT NULL DEFAULT 0
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
            toasted INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        )
    """)

    # Create holdings table (referenced by reset_account)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS holdings (
            id INTEGER PRIMARY KEY,
            user_id INTEGER NOT NULL,
            ore_name TEXT NOT NULL,
            quantity REAL NOT NULL DEFAULT 0,
            avg_price REAL NOT NULL DEFAULT 0,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    """)

    # Create transactions table (referenced by reset_account)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY,
            user_id INTEGER NOT NULL,
            type TEXT NOT NULL,
            archived INTEGER NOT NULL DEFAULT 0,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    """)

    # Create short_positions table (referenced by reset_account)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS short_positions (
            id INTEGER PRIMARY KEY,
            user_id INTEGER NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    """)

    # Create stop_loss_take_profit table (referenced by reset_account)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS stop_loss_take_profit (
            id INTEGER PRIMARY KEY,
            holding_id INTEGER NOT NULL,
            FOREIGN KEY (holding_id) REFERENCES holdings(id)
        )
    """)

    # Create tutorial_progress table (referenced by reset_account)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS tutorial_progress (
            id INTEGER PRIMARY KEY,
            user_id INTEGER NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    """)

    # Create push_subscriptions table (referenced by reset_account)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS push_subscriptions (
            id INTEGER PRIMARY KEY,
            user_id INTEGER NOT NULL
        )
    """)

    # Create indexes
    conn.execute("CREATE INDEX IF NOT EXISTS idx_notifications_user_read ON notifications(user_id, is_read)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_notifications_user_id_desc ON notifications(user_id, id DESC)")

    # Insert test users (user 1 is the target, user 2 is the "other" user)
    conn.execute(
        "INSERT INTO users (id, username, password_hash) VALUES (1, 'testuser', 'hash123')"
    )
    conn.execute(
        "INSERT INTO users (id, username, password_hash) VALUES (2, 'otheruser', 'hash456')"
    )
    conn.commit()
    return conn


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

notification_category = st.sampled_from([
    "achievement", "liquidation", "trade", "system", "alert", "info"
])

notification_message = st.text(min_size=1, max_size=100).filter(lambda s: s.strip())


# ---------------------------------------------------------------------------
# Feature: notification-system, Property 11: Account reset removes all notifications
# Validates: Requirements 10.1
# ---------------------------------------------------------------------------


@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture, HealthCheck.too_slow])
@given(
    num_notifications=st.integers(min_value=1, max_value=20),
    categories=st.lists(notification_category, min_size=20, max_size=20),
    messages=st.lists(notification_message, min_size=20, max_size=20),
    num_other_notifications=st.integers(min_value=0, max_value=5),
)
def test_account_reset_removes_all_notifications(
    num_notifications, categories, messages, num_other_notifications
):
    """Property 11: For any user with notifications, calling reset_account
    results in zero notifications remaining for that user. Notifications
    for other users are NOT affected.

    **Validates: Requirements 10.1**
    """
    db = _create_test_db()
    try:
        # Insert notifications for user 1 (the target user)
        for i in range(num_notifications):
            db.execute(
                "INSERT INTO notifications (user_id, category, message) VALUES (?, ?, ?)",
                (1, categories[i], messages[i])
            )

        # Insert notifications for user 2 (should not be affected)
        for i in range(num_other_notifications):
            db.execute(
                "INSERT INTO notifications (user_id, category, message) VALUES (?, ?, ?)",
                (2, categories[i], messages[i])
            )
        db.commit()

        # Verify notifications were inserted for user 1
        count_before = db.execute(
            "SELECT COUNT(*) as cnt FROM notifications WHERE user_id = 1"
        ).fetchone()["cnt"]
        assert count_before == num_notifications

        # Count other user's notifications before reset
        other_count_before = db.execute(
            "SELECT COUNT(*) as cnt FROM notifications WHERE user_id = 2"
        ).fetchone()["cnt"]
        assert other_count_before == num_other_notifications

        # Mock get_db and current_app for reset_account
        mock_app = MagicMock()
        mock_app.config = {'DEFAULT_BALANCE': 10000.0}

        with patch('app.models.get_db', return_value=db), \
             patch('app.models.current_app', mock_app):
            reset_account(1)

        # Verify all notifications for user 1 are deleted
        count_after = db.execute(
            "SELECT COUNT(*) as cnt FROM notifications WHERE user_id = 1"
        ).fetchone()["cnt"]
        assert count_after == 0, (
            f"Expected 0 notifications for user 1 after reset, got {count_after}"
        )

        # Verify notifications for user 2 are NOT affected
        other_count_after = db.execute(
            "SELECT COUNT(*) as cnt FROM notifications WHERE user_id = 2"
        ).fetchone()["cnt"]
        assert other_count_after == other_count_before, (
            f"Other user's notifications changed from {other_count_before} to "
            f"{other_count_after} after reset_account for user 1"
        )
    finally:
        db.close()
