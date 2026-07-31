"""Integration tests for advancement lifecycle.

Requirements validated: 4.1, 5.1, 10.1, 16.1, 16.5
"""
import sqlite3

import pytest

from conftest import register_user

pytestmark = pytest.mark.advancements_integration


@pytest.fixture(autouse=True)
def clean_advancements(app):
    """Clear the advancements and notifications tables before each test.

    The shared db_reset fixture does not drop these tables, so we must
    clear them explicitly to prevent cross-test contamination.
    """
    db_path = app.config["DATABASE_PATH"]
    conn = sqlite3.connect(db_path)
    conn.execute("DELETE FROM advancements")
    conn.execute("DELETE FROM notifications")
    conn.commit()
    conn.close()
    yield


def test_full_award_lifecycle(app, client):
    """Full award lifecycle: Create user → trigger condition → verify advancement row + notification.

    Validates: Requirements 4.1
    """
    from app.advancements import award_advancement, has_advancement, get_user_advancements

    # Register a user
    register_user(client, "lifecycle_user", "Password123!")

    with app.app_context():
        db_path = app.config["DATABASE_PATH"]
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row

        # Get the user id
        user_row = conn.execute(
            "SELECT id FROM users WHERE username = ?", ("lifecycle_user",)
        ).fetchone()
        assert user_row is not None
        user_id = user_row["id"]

        # Verify no advancements initially
        assert has_advancement(conn, user_id, "millionaire") is False
        advs = get_user_advancements(conn, user_id)
        assert len(advs) == 0

        # Award a millionaire advancement directly
        result = award_advancement(conn, user_id, "millionaire")
        conn.commit()

        # Verify it was newly awarded
        assert result is True

        # Verify the advancement row exists
        assert has_advancement(conn, user_id, "millionaire") is True
        advs = get_user_advancements(conn, user_id)
        assert len(advs) == 1
        assert advs[0]["key"] == "millionaire"
        assert advs[0]["earned_at"] is not None

        # Verify notification was created
        notif_row = conn.execute(
            "SELECT * FROM notifications WHERE user_id = ? AND category = 'advancement'",
            (user_id,),
        ).fetchone()
        assert notif_row is not None
        assert "Millionaire" in notif_row["message"]

        # Verify idempotency — awarding again returns False
        result2 = award_advancement(conn, user_id, "millionaire")
        assert result2 is False

        conn.close()


def test_tick_engine_evaluation_millionaire(app, client):
    """Tick engine evaluation: Set user at $1M net worth → run evaluate_tick_advancements → verify millionaire awarded.

    Validates: Requirements 4.1, 5.1
    """
    from app.advancements import evaluate_tick_advancements, has_advancement

    # Register a user
    register_user(client, "tick_user", "Password123!")

    with app.app_context():
        db_path = app.config["DATABASE_PATH"]
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row

        # Get the user id
        user_row = conn.execute(
            "SELECT id FROM users WHERE username = ?", ("tick_user",)
        ).fetchone()
        assert user_row is not None
        user_id = user_row["id"]

        # Verify no millionaire advancement initially
        assert has_advancement(conn, user_id, "millionaire") is False

        # Set user balance to $1,000,000 (net worth = balance when no holdings)
        conn.execute(
            "UPDATE users SET balance = ? WHERE id = ?", (1_000_000, user_id)
        )
        conn.commit()

        # Run tick evaluation
        evaluate_tick_advancements(conn)
        conn.commit()

        # Verify millionaire was awarded
        assert has_advancement(conn, user_id, "millionaire") is True

        # Verify notification was created
        notif_row = conn.execute(
            "SELECT * FROM notifications WHERE user_id = ? AND category = 'advancement' AND message LIKE '%Millionaire%'",
            (user_id,),
        ).fetchone()
        assert notif_row is not None

        conn.close()


def test_completionist_cascade(app, client):
    """Completionist cascade: Award 8 advancements sequentially → verify completionist auto-awarded on 8th.

    Validates: Requirements 10.1
    """
    from app.advancements import award_advancement, has_advancement, ADVANCEMENT_KEYS

    # Register a user
    register_user(client, "completionist_user", "Password123!")

    with app.app_context():
        db_path = app.config["DATABASE_PATH"]
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row

        # Get the user id
        user_row = conn.execute(
            "SELECT id FROM users WHERE username = ?", ("completionist_user",)
        ).fetchone()
        assert user_row is not None
        user_id = user_row["id"]

        # Get all keys except completionist
        non_completionist_keys = [k for k in ADVANCEMENT_KEYS if k != "completionist"]
        assert len(non_completionist_keys) == 8

        # Award 7 of the 8 advancements — completionist should NOT yet be awarded
        for key in non_completionist_keys[:7]:
            award_advancement(conn, user_id, key)
            conn.commit()

        assert has_advancement(conn, user_id, "completionist") is False

        # Award the 8th advancement — completionist should auto-trigger
        award_advancement(conn, user_id, non_completionist_keys[7])
        conn.commit()

        assert has_advancement(conn, user_id, "completionist") is True

        # Verify completionist notification was created
        notif_row = conn.execute(
            "SELECT * FROM notifications WHERE user_id = ? AND category = 'advancement' AND message LIKE '%Completionist%'",
            (user_id,),
        ).fetchone()
        assert notif_row is not None
        assert "Gold theme unlocked" in notif_row["message"]

        # Verify gold_theme_unlocked was set
        theme_row = conn.execute(
            "SELECT gold_theme_unlocked FROM users WHERE id = ?", (user_id,)
        ).fetchone()
        assert theme_row["gold_theme_unlocked"] == 1

        conn.close()


def test_account_reset_preserves_advancements(app, client):
    """Account reset preservation: Earn advancements → reset → verify advancements intact, play_time/streak zeroed.

    Validates: Requirements 16.1
    """
    from app.advancements import award_advancement, has_advancement, get_user_advancements
    from app.models import reset_account

    # Register a user
    register_user(client, "reset_user", "Password123!")

    with app.app_context():
        db_path = app.config["DATABASE_PATH"]
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row

        # Get the user id
        user_row = conn.execute(
            "SELECT id FROM users WHERE username = ?", ("reset_user",)
        ).fetchone()
        assert user_row is not None
        user_id = user_row["id"]

        # Set play_time and login_streak to non-zero values
        conn.execute(
            "UPDATE users SET play_time = 50, login_streak = 5, last_streak_date = '2024-01-15' WHERE id = ?",
            (user_id,),
        )
        conn.commit()

        # Award some advancements
        award_advancement(conn, user_id, "millionaire")
        award_advancement(conn, user_id, "dedicated")
        award_advancement(conn, user_id, "the_big_short")
        conn.commit()

        # Verify advancements exist before reset
        advs_before = get_user_advancements(conn, user_id)
        assert len(advs_before) == 3
        conn.close()

        # Perform reset — uses Flask's get_db() so needs app context
        reset_account(user_id)

        # Reconnect and verify
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row

        # Advancements should still be intact
        advs_after = get_user_advancements(conn, user_id)
        assert len(advs_after) == 3
        assert has_advancement(conn, user_id, "millionaire") is True
        assert has_advancement(conn, user_id, "dedicated") is True
        assert has_advancement(conn, user_id, "the_big_short") is True

        # play_time and login_streak should be zeroed
        user_after = conn.execute(
            "SELECT play_time, login_streak, last_streak_date FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()
        assert user_after["play_time"] == 0
        assert user_after["login_streak"] == 0
        assert user_after["last_streak_date"] is None

        conn.close()


def test_account_delete_removes_advancements(app, client):
    """Account delete cleanup: Earn advancements → delete → verify zero rows in advancements table for that user.

    Validates: Requirements 16.5
    """
    from app.advancements import award_advancement
    from app.models import delete_account

    # Register a user
    register_user(client, "delete_user", "Password123!")

    with app.app_context():
        db_path = app.config["DATABASE_PATH"]
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row

        # Get the user id
        user_row = conn.execute(
            "SELECT id FROM users WHERE username = ?", ("delete_user",)
        ).fetchone()
        assert user_row is not None
        user_id = user_row["id"]

        # Award advancements
        award_advancement(conn, user_id, "millionaire")
        award_advancement(conn, user_id, "multimillionaire")
        award_advancement(conn, user_id, "dedicated")
        conn.commit()

        # Verify advancements exist
        count_row = conn.execute(
            "SELECT COUNT(*) as cnt FROM advancements WHERE user_id = ?",
            (user_id,),
        ).fetchone()
        assert count_row["cnt"] == 3
        conn.close()

        # Delete the account — uses Flask's get_db() internally
        delete_account(user_id)

        # Reconnect and verify advancements are gone
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row

        # User row should be gone
        user_check = conn.execute(
            "SELECT id FROM users WHERE id = ?", (user_id,)
        ).fetchone()
        assert user_check is None

        # Advancements should be gone (CASCADE delete)
        adv_count = conn.execute(
            "SELECT COUNT(*) as cnt FROM advancements WHERE user_id = ?",
            (user_id,),
        ).fetchone()
        assert adv_count["cnt"] == 0

        conn.close()
