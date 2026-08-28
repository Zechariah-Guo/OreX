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
    from app.database import get_db

    # Register a user
    register_user(client, "lifecycle_user", "Password123!")

    with app.app_context():
        db = get_db()

        # Get the user id
        user_row = db.execute(
            "SELECT id FROM users WHERE username = ?", ("lifecycle_user",)
        ).fetchone()
        assert user_row is not None
        user_id = user_row["id"]

        # Verify no advancements initially
        assert has_advancement(db, user_id, "millionaire") is False
        advs = get_user_advancements(db, user_id)
        assert len(advs) == 0

        # Award a millionaire advancement directly
        result = award_advancement(db, user_id, "millionaire")
        db.commit()

        # Verify it was newly awarded
        assert result is True

        # Verify the advancement row exists
        assert has_advancement(db, user_id, "millionaire") is True
        advs = get_user_advancements(db, user_id)
        assert len(advs) == 1
        assert advs[0]["key"] == "millionaire"
        assert advs[0]["earned_at"] is not None

        # Verify notification was created (create_notification uses get_db() internally,
        # which returns the same connection since we're in the same app context)
        notif_row = db.execute(
            "SELECT * FROM notifications WHERE user_id = ? AND category = 'advancement'",
            (user_id,),
        ).fetchone()
        assert notif_row is not None
        assert "Millionaire" in notif_row["message"]

        # Verify idempotency — awarding again returns False
        result2 = award_advancement(db, user_id, "millionaire")
        assert result2 is False


def test_tick_engine_evaluation_millionaire(app, client):
    """Tick engine evaluation: Set user at $1M net worth → run evaluate_tick_advancements → verify millionaire awarded.

    Validates: Requirements 4.1, 5.1
    """
    from app.advancements import evaluate_tick_advancements, has_advancement
    from app.database import get_db

    # Register a user
    register_user(client, "tick_user", "Password123!")

    with app.app_context():
        db = get_db()

        # Get the user id
        user_row = db.execute(
            "SELECT id FROM users WHERE username = ?", ("tick_user",)
        ).fetchone()
        assert user_row is not None
        user_id = user_row["id"]

        # Verify no millionaire advancement initially
        assert has_advancement(db, user_id, "millionaire") is False

        # Set user balance to $1,000,000 (net worth = balance when no holdings)
        db.execute(
            "UPDATE users SET balance = ? WHERE id = ?", (1_000_000, user_id)
        )
        db.commit()

        # Run tick evaluation
        evaluate_tick_advancements(db)
        db.commit()

        # Verify millionaire was awarded
        assert has_advancement(db, user_id, "millionaire") is True

        # Verify notification was created
        notif_row = db.execute(
            "SELECT * FROM notifications WHERE user_id = ? AND category = 'advancement' AND message LIKE '%Millionaire%'",
            (user_id,),
        ).fetchone()
        assert notif_row is not None


def test_completionist_cascade(app, client):
    """Completionist cascade: Award 8 advancements sequentially → verify completionist auto-awarded on 8th.

    Validates: Requirements 10.1
    """
    from app.advancements import award_advancement, has_advancement, ADVANCEMENT_KEYS
    from app.database import get_db

    # Register a user
    register_user(client, "completionist_user", "Password123!")

    with app.app_context():
        db = get_db()

        # Get the user id
        user_row = db.execute(
            "SELECT id FROM users WHERE username = ?", ("completionist_user",)
        ).fetchone()
        assert user_row is not None
        user_id = user_row["id"]

        # Get all keys except completionist
        non_completionist_keys = [k for k in ADVANCEMENT_KEYS if k != "completionist"]
        assert len(non_completionist_keys) == 8

        # Award 7 of the 8 advancements — completionist should NOT yet be awarded
        for key in non_completionist_keys[:7]:
            award_advancement(db, user_id, key)
            db.commit()

        assert has_advancement(db, user_id, "completionist") is False

        # Award the 8th advancement — completionist should auto-trigger
        award_advancement(db, user_id, non_completionist_keys[7])
        db.commit()

        assert has_advancement(db, user_id, "completionist") is True

        # Verify completionist notification was created
        notif_row = db.execute(
            "SELECT * FROM notifications WHERE user_id = ? AND category = 'advancement' AND message LIKE '%Completionist%'",
            (user_id,),
        ).fetchone()
        assert notif_row is not None
        assert "Gold theme unlocked" in notif_row["message"]

        # Verify gold_theme_unlocked was set
        theme_row = db.execute(
            "SELECT gold_theme_unlocked FROM users WHERE id = ?", (user_id,)
        ).fetchone()
        assert theme_row["gold_theme_unlocked"] == 1


def test_account_reset_preserves_advancements(app, client):
    """Account reset preservation: Earn advancements → reset → verify advancements intact, play_time/streak zeroed.

    Validates: Requirements 16.1
    """
    from app.advancements import award_advancement, has_advancement, get_user_advancements
    from app.models import reset_account
    from app.database import get_db

    # Register a user
    register_user(client, "reset_user", "Password123!")

    with app.app_context():
        db = get_db()

        # Get the user id
        user_row = db.execute(
            "SELECT id FROM users WHERE username = ?", ("reset_user",)
        ).fetchone()
        assert user_row is not None
        user_id = user_row["id"]

        # Set play_time and login_streak to non-zero values
        db.execute(
            "UPDATE users SET play_time = 50, login_streak = 5, last_streak_date = '2024-01-15' WHERE id = ?",
            (user_id,),
        )
        db.commit()

        # Award some advancements
        award_advancement(db, user_id, "millionaire")
        award_advancement(db, user_id, "dedicated")
        award_advancement(db, user_id, "the_big_short")
        db.commit()

        # Verify advancements exist before reset
        advs_before = get_user_advancements(db, user_id)
        assert len(advs_before) == 3

        # Perform reset — uses Flask's get_db() internally (same connection)
        reset_account(user_id)

        # Advancements should still be intact
        advs_after = get_user_advancements(db, user_id)
        assert len(advs_after) == 3
        assert has_advancement(db, user_id, "millionaire") is True
        assert has_advancement(db, user_id, "dedicated") is True
        assert has_advancement(db, user_id, "the_big_short") is True

        # play_time and login_streak should be PRESERVED (player is still playing)
        user_after = db.execute(
            "SELECT play_time, login_streak, last_streak_date FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()
        assert user_after["play_time"] == 50
        assert user_after["login_streak"] == 5
        assert user_after["last_streak_date"] == "2024-01-15"


def test_account_delete_removes_advancements(app, client):
    """Account delete cleanup: Earn advancements → delete → verify zero rows in advancements table for that user.

    Validates: Requirements 16.5
    """
    from app.advancements import award_advancement
    from app.models import delete_account
    from app.database import get_db

    # Register a user
    register_user(client, "delete_user", "Password123!")

    with app.app_context():
        db = get_db()

        # Get the user id
        user_row = db.execute(
            "SELECT id FROM users WHERE username = ?", ("delete_user",)
        ).fetchone()
        assert user_row is not None
        user_id = user_row["id"]

        # Award advancements
        award_advancement(db, user_id, "millionaire")
        award_advancement(db, user_id, "multimillionaire")
        award_advancement(db, user_id, "dedicated")
        db.commit()

        # Verify advancements exist
        count_row = db.execute(
            "SELECT COUNT(*) as cnt FROM advancements WHERE user_id = ?",
            (user_id,),
        ).fetchone()
        assert count_row["cnt"] == 3

        # Delete the account — uses Flask's get_db() internally (same connection)
        delete_account(user_id)

        # User row should be gone
        user_check = db.execute(
            "SELECT id FROM users WHERE id = ?", (user_id,)
        ).fetchone()
        assert user_check is None

        # Advancements should be gone (CASCADE delete)
        adv_count = db.execute(
            "SELECT COUNT(*) as cnt FROM advancements WHERE user_id = ?",
            (user_id,),
        ).fetchone()
        assert adv_count["cnt"] == 0
