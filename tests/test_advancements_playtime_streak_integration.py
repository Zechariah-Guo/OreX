"""Integration tests for play time accumulation and login streak transitions.

Requirements validated: 2.2, 3.2, 7.1, 9.1
"""

import sqlite3
import datetime
from unittest.mock import patch

import pytest

from conftest import register_user

pytestmark = pytest.mark.advancements_integration


def _get_db(app):
    """Open a direct SQLite connection to the test database with Row factory."""
    conn = sqlite3.connect(app.config["DATABASE_PATH"])
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


@pytest.fixture(autouse=True)
def _clear_advancements(app):
    """Ensure the advancements table is empty before each test.

    The global db_reset fixture does not drop the advancements/notifications
    tables (they were added after the initial fixture), so we clear them
    explicitly to prevent cross-test contamination.
    """
    conn = sqlite3.connect(app.config["DATABASE_PATH"])
    conn.execute("DELETE FROM advancements")
    conn.execute("DELETE FROM notifications")
    conn.commit()
    conn.close()
    yield


def _create_user(client, app, username="PlayTimeUser", password="TestPass123!"):
    """Register a user and return their user_id."""
    register_user(client, username, password)
    conn = _get_db(app)
    row = conn.execute(
        "SELECT id FROM users WHERE username = ?", (username,)
    ).fetchone()
    conn.close()
    return row["id"]


class TestPlayTimeAccumulation:
    """Test that play_time increments correctly and budding_enthusiast is awarded at 20 min.

    **Validates: Requirements 2.2, 7.1**
    """

    def test_flush_playtime_increments_and_awards_budding_enthusiast(self, client, app):
        """Simulate heartbeats via flush_playtime, verify play_time increments,
        then verify budding_enthusiast (suit_up) is awarded at 20 minutes."""
        from app.playtime import flush_playtime
        from app.advancements import evaluate_playtime_advancement, has_advancement

        user_id = _create_user(client, app, "PlayTimeUser1", "TestPass123!")
        conn = _get_db(app)

        # Flush 15 minutes — should NOT award budding_enthusiast yet
        flush_playtime(conn, user_id, 15)
        conn.commit()

        row = conn.execute(
            "SELECT play_time FROM users WHERE id = ?", (user_id,)
        ).fetchone()
        assert row["play_time"] == 15

        # Evaluate — should NOT award yet (15 < 20)
        evaluate_playtime_advancement(conn, user_id)
        conn.commit()
        assert has_advancement(conn, user_id, "budding_enthusiast") is False

        # Flush 5 more minutes (total = 20) — should award budding_enthusiast
        flush_playtime(conn, user_id, 5)
        conn.commit()

        row = conn.execute(
            "SELECT play_time FROM users WHERE id = ?", (user_id,)
        ).fetchone()
        assert row["play_time"] == 20

        evaluate_playtime_advancement(conn, user_id)
        conn.commit()
        assert has_advancement(conn, user_id, "budding_enthusiast") is True

        conn.close()

    def test_playtime_beyond_threshold_still_awards(self, client, app):
        """Verify that if play_time goes well beyond 20, the advancement is still awarded."""
        from app.playtime import flush_playtime
        from app.advancements import evaluate_playtime_advancement, has_advancement

        user_id = _create_user(client, app, "PlayTimeUser2", "TestPass123!")
        conn = _get_db(app)

        # Flush 25 minutes in one go (exceeds 20)
        flush_playtime(conn, user_id, 25)
        conn.commit()

        evaluate_playtime_advancement(conn, user_id)
        conn.commit()
        assert has_advancement(conn, user_id, "budding_enthusiast") is True

        conn.close()


class TestLoginStreakTransitions:
    """Test that login streak increments across multiple days and awards dedicated at 3.

    **Validates: Requirements 3.2, 9.1**
    """

    def test_login_streak_increments_and_awards_dedicated(self, client, app):
        """Simulate multi-day logins with mocked dates, verify streak increments,
        and verify 'dedicated' advancement is awarded at 3 consecutive days."""
        from app.advancements import update_login_streak, has_advancement

        user_id = _create_user(client, app, "StreakUser1", "TestPass123!")
        conn = _get_db(app)

        base_date = datetime.date(2024, 6, 10)

        # Day 1: First login — streak should become 1
        with patch("app.advancements.datetime") as mock_dt:
            mock_dt.date.today.return_value = base_date
            mock_dt.date.fromisoformat = datetime.date.fromisoformat
            update_login_streak(conn, user_id)
            conn.commit()

        row = conn.execute(
            "SELECT login_streak, last_streak_date FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()
        assert row["login_streak"] == 1
        assert row["last_streak_date"] == "2024-06-10"
        assert has_advancement(conn, user_id, "dedicated") is False

        # Day 2: Login next day — streak should become 2
        with patch("app.advancements.datetime") as mock_dt:
            mock_dt.date.today.return_value = base_date + datetime.timedelta(days=1)
            mock_dt.date.fromisoformat = datetime.date.fromisoformat
            update_login_streak(conn, user_id)
            conn.commit()

        row = conn.execute(
            "SELECT login_streak FROM users WHERE id = ?", (user_id,)
        ).fetchone()
        assert row["login_streak"] == 2
        assert has_advancement(conn, user_id, "dedicated") is False

        # Day 3: Login next day — streak should become 3 → "dedicated" awarded
        with patch("app.advancements.datetime") as mock_dt:
            mock_dt.date.today.return_value = base_date + datetime.timedelta(days=2)
            mock_dt.date.fromisoformat = datetime.date.fromisoformat
            update_login_streak(conn, user_id)
            conn.commit()

        row = conn.execute(
            "SELECT login_streak FROM users WHERE id = ?", (user_id,)
        ).fetchone()
        assert row["login_streak"] == 3
        assert has_advancement(conn, user_id, "dedicated") is True

        conn.close()

    def test_streak_resets_after_gap(self, client, app):
        """Verify that a gap of more than 1 day resets the streak to 1."""
        from app.advancements import update_login_streak, has_advancement

        user_id = _create_user(client, app, "StreakUser2", "TestPass123!")
        conn = _get_db(app)

        # Verify clean state — no advancements should exist yet
        assert has_advancement(conn, user_id, "dedicated") is False

        base_date = datetime.date(2024, 6, 10)

        # Day 1: First login
        with patch("app.advancements.datetime") as mock_dt:
            mock_dt.date.today.return_value = base_date
            mock_dt.date.fromisoformat = datetime.date.fromisoformat
            update_login_streak(conn, user_id)
            conn.commit()

        row = conn.execute(
            "SELECT login_streak FROM users WHERE id = ?", (user_id,)
        ).fetchone()
        assert row["login_streak"] == 1

        # Day 2: Login next day — streak becomes 2
        with patch("app.advancements.datetime") as mock_dt:
            mock_dt.date.today.return_value = base_date + datetime.timedelta(days=1)
            mock_dt.date.fromisoformat = datetime.date.fromisoformat
            update_login_streak(conn, user_id)
            conn.commit()

        row = conn.execute(
            "SELECT login_streak FROM users WHERE id = ?", (user_id,)
        ).fetchone()
        assert row["login_streak"] == 2

        # Day 5: Login after 3-day gap — streak resets to 1
        with patch("app.advancements.datetime") as mock_dt:
            mock_dt.date.today.return_value = base_date + datetime.timedelta(days=4)
            mock_dt.date.fromisoformat = datetime.date.fromisoformat
            update_login_streak(conn, user_id)
            conn.commit()

        row = conn.execute(
            "SELECT login_streak FROM users WHERE id = ?", (user_id,)
        ).fetchone()
        assert row["login_streak"] == 1
        assert has_advancement(conn, user_id, "dedicated") is False

        conn.close()
