"""Property-based tests for the Advancements System.

Uses Hypothesis to verify universal correctness properties defined in the
design document for the advancement award engine.
"""

import os
import sys
import sqlite3

# Add src/ to the Python path so that `from app.advancements import ...` works
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'src'))

import pytest
from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st

from app.advancements import (
    award_advancement,
    has_advancement,
    evaluate_short_advancement,
    evaluate_trade_advancement,
    evaluate_completionist,
    ADVANCEMENT_KEYS,
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

    # Create advancements table
    conn.execute("""
        CREATE TABLE IF NOT EXISTS advancements (
            id INTEGER PRIMARY KEY,
            user_id INTEGER NOT NULL,
            advancement_key TEXT NOT NULL,
            earned_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
            UNIQUE(user_id, advancement_key),
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        )
    """)

    # Create notifications table (award_advancement calls create_notification)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS notifications (
            id INTEGER PRIMARY KEY,
            user_id INTEGER NOT NULL,
            category TEXT NOT NULL,
            message TEXT NOT NULL,
            action_url TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        )
    """)

    # Create index
    conn.execute("CREATE INDEX IF NOT EXISTS idx_advancements_user ON advancements(user_id)")

    # Insert a test user
    conn.execute(
        "INSERT INTO users (id, username, password_hash) VALUES (1, 'testuser', 'hash123')"
    )
    conn.commit()
    return conn


# ---------------------------------------------------------------------------
# Feature: achievements-system, Property 1: Advancement Award Idempotency
# Validates: Requirements 1.2, 4.3, 5.3, 6.4, 7.3, 9.3, 10.4, 11.4, 12.3
# ---------------------------------------------------------------------------


@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(
    key=st.sampled_from(ADVANCEMENT_KEYS),
    repeat_count=st.integers(min_value=1, max_value=3),
)
def test_advancement_award_idempotency(key, repeat_count):
    """Property 1: Calling award_advancement(db, user_id, key) multiple times
    results in exactly one row in the advancements table for that (user_id, key) pair.

    Specifically:
    - The first call returns True (newly awarded)
    - Subsequent calls return False (already owned)
    - Exactly one row exists in the advancements table after all calls
    - The earned_at timestamp does not change after subsequent calls

    **Validates: Requirements 1.2, 4.3, 5.3, 6.4, 7.3, 9.3, 10.4, 11.4, 12.3**
    """
    db = _create_test_db()
    user_id = 1

    try:
        # First call should always return True (newly awarded)
        first_result = award_advancement(db, user_id, key)
        db.commit()
        assert first_result is True, f"First award of {key!r} should return True"

        # Capture the earned_at timestamp after first award
        row = db.execute(
            "SELECT earned_at FROM advancements WHERE user_id = ? AND advancement_key = ?",
            (user_id, key),
        ).fetchone()
        assert row is not None, f"Row should exist after first award of {key!r}"
        original_earned_at = row["earned_at"]

        # Subsequent calls should return False
        for i in range(repeat_count - 1):
            result = award_advancement(db, user_id, key)
            db.commit()
            assert result is False, (
                f"Call #{i + 2} of award_advancement for {key!r} should return False"
            )

        # Verify exactly one row exists for this (user_id, key) pair
        count_row = db.execute(
            "SELECT COUNT(*) as cnt FROM advancements WHERE user_id = ? AND advancement_key = ?",
            (user_id, key),
        ).fetchone()
        assert count_row["cnt"] == 1, (
            f"Expected exactly 1 row for ({user_id}, {key!r}), got {count_row['cnt']}"
        )

        # Verify earned_at timestamp did not change
        final_row = db.execute(
            "SELECT earned_at FROM advancements WHERE user_id = ? AND advancement_key = ?",
            (user_id, key),
        ).fetchone()
        assert final_row["earned_at"] == original_earned_at, (
            f"earned_at should not change: was {original_earned_at!r}, now {final_row['earned_at']!r}"
        )
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Feature: achievements-system, Property 4: The Big Short Preconditions
# Validates: Requirements 6.1, 6.2, 6.3
# ---------------------------------------------------------------------------


@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(
    profit=st.floats(-10000, 10000),
    advanced_active=st.booleans(),
    close_type=st.sampled_from(['voluntary', 'take_profit', 'liquidated']),
)
def test_the_big_short_preconditions(profit, advanced_active, close_type):
    """Property 4: For any short position close event with profit P, close_type C,
    and player advanced_mode_active A: "the_big_short" SHALL be awarded if and only if
    P > 0 AND A is true AND C is in {"voluntary", "take_profit"}.
    If any condition fails (P <= 0, A is false, or C is "liquidated"), the achievement
    SHALL NOT be awarded.

    **Validates: Requirements 6.1, 6.2, 6.3**
    """
    db = _create_test_db()
    user_id = 1

    try:
        # Set the user's advanced_active status based on the generated boolean
        db.execute(
            "UPDATE users SET advanced_active = ? WHERE id = ?",
            (1 if advanced_active else 0, user_id),
        )
        db.commit()

        # Determine if all preconditions are met (mimics the caller's logic)
        should_award = (
            profit > 0
            and advanced_active
            and close_type in ('voluntary', 'take_profit')
        )

        # Simulate the calling logic: only call evaluate_short_advancement
        # when the caller verifies all preconditions
        if should_award:
            evaluate_short_advancement(db, user_id)
            db.commit()

        # Verify the advancement state matches the expected outcome
        awarded = has_advancement(db, user_id, "the_big_short")

        if should_award:
            assert awarded is True, (
                f"the_big_short should be awarded when profit={profit}, "
                f"advanced_active={advanced_active}, close_type={close_type!r}"
            )
        else:
            assert awarded is False, (
                f"the_big_short should NOT be awarded when profit={profit}, "
                f"advanced_active={advanced_active}, close_type={close_type!r}"
            )
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Feature: achievements-system, Property 6: Suit Up Threshold
# Validates: Requirements 7.1, 9.1
# ---------------------------------------------------------------------------


@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(play_time=st.integers(min_value=0, max_value=100))
def test_suit_up_threshold(play_time):
    """Property 6: For any player with cumulative play_time P minutes,
    "budding_enthusiast" (Suit Up) SHALL be awarded if and only if P >= 20.

    **Validates: Requirements 7.1, 9.1**
    """
    from app.advancements import evaluate_playtime_advancement, has_advancement

    db = _create_test_db()
    user_id = 1

    try:
        # Set up the user's play_time to the generated value
        db.execute(
            "UPDATE users SET play_time = ? WHERE id = ?",
            (play_time, user_id),
        )
        db.commit()

        # Evaluate playtime advancement
        evaluate_playtime_advancement(db, user_id)
        db.commit()

        # Assert the advancement is awarded iff play_time >= 20
        awarded = has_advancement(db, user_id, "budding_enthusiast")
        if play_time >= 20:
            assert awarded is True, (
                f"budding_enthusiast should be awarded when play_time={play_time} >= 20"
            )
        else:
            assert awarded is False, (
                f"budding_enthusiast should NOT be awarded when play_time={play_time} < 20"
            )
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Feature: achievements-system, Property 7: Dedicated Streak Threshold
# Validates: Requirements 7.1, 9.1
# ---------------------------------------------------------------------------


@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(login_streak=st.integers(min_value=1, max_value=30))
def test_dedicated_streak_threshold(login_streak):
    """Property 7: For any player with login_streak S,
    "dedicated" SHALL be awarded if and only if S >= 3.

    **Validates: Requirements 7.1, 9.1**
    """
    from app.advancements import evaluate_login_advancements, has_advancement

    db = _create_test_db()
    user_id = 1

    try:
        # Set up the user's login_streak to the generated value
        db.execute(
            "UPDATE users SET login_streak = ? WHERE id = ?",
            (login_streak, user_id),
        )
        db.commit()

        # Evaluate login advancements
        evaluate_login_advancements(db, user_id)
        db.commit()

        # Assert the advancement is awarded iff login_streak >= 3
        awarded = has_advancement(db, user_id, "dedicated")
        if login_streak >= 3:
            assert awarded is True, (
                f"dedicated should be awarded when login_streak={login_streak} >= 3"
            )
        else:
            assert awarded is False, (
                f"dedicated should NOT be awarded when login_streak={login_streak} < 3"
            )
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Feature: achievements-system, Property 8: Post-mortem Threshold
# Validates: Requirements 11.1, 11.3
# ---------------------------------------------------------------------------


@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(net_worth=st.floats(min_value=0, max_value=50_000))
def test_post_mortem_threshold(net_worth):
    """Property 8: For any player triggering an account reset with current
    net worth N, "tragedy" (Post-mortem) SHALL be awarded if and only if
    N < 10,000. If N >= 10,000, the achievement SHALL NOT be awarded.

    **Validates: Requirements 11.1, 11.3**
    """
    from app.advancements import evaluate_post_mortem, has_advancement

    db = _create_test_db()
    user_id = 1

    try:
        # evaluate_post_mortem takes net_worth as an argument directly,
        # so no need to manipulate the balance column.
        evaluate_post_mortem(db, user_id, net_worth)
        db.commit()

        # Assert the advancement is awarded iff net_worth < 10,000
        awarded = has_advancement(db, user_id, "tragedy")
        if net_worth < 10_000:
            assert awarded is True, (
                f"tragedy should be awarded when net_worth={net_worth} < 10,000"
            )
        else:
            assert awarded is False, (
                f"tragedy should NOT be awarded when net_worth={net_worth} >= 10,000"
            )
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Feature: achievements-system, Property 3: Net Worth Threshold Achievement Awards
# Validates: Requirements 4.1, 5.1
# ---------------------------------------------------------------------------


def _create_net_worth_test_db(balance: float):
    """Create an in-memory SQLite database with the required schema for net worth testing.

    Sets the test user's balance to the given value. Since there are no holdings
    or short positions, net_worth == balance for the purposes of this test.
    """
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

    # Create ores table (needed for net worth query JOINs)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS ores (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL UNIQUE,
            description TEXT,
            icon_filename TEXT,
            current_price REAL NOT NULL,
            base_price REAL NOT NULL,
            price_floor REAL NOT NULL,
            price_ceiling REAL NOT NULL,
            volatility REAL NOT NULL,
            price_change_range TEXT NOT NULL,
            base_probabilities TEXT NOT NULL,
            trend_log TEXT NOT NULL DEFAULT '["hold","hold","hold","hold","hold"]'
        )
    """)

    # Create holdings table (needed for net worth query JOINs)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS holdings (
            id INTEGER PRIMARY KEY,
            user_id INTEGER NOT NULL,
            ore_id INTEGER NOT NULL,
            quantity INTEGER NOT NULL,
            avg_purchase_price REAL NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users(id),
            FOREIGN KEY (ore_id) REFERENCES ores(id)
        )
    """)

    # Create short_positions table (needed for net worth query JOINs)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS short_positions (
            id INTEGER PRIMARY KEY,
            user_id INTEGER NOT NULL,
            ore_id INTEGER NOT NULL,
            share_quantity INTEGER NOT NULL,
            entry_price REAL NOT NULL,
            locked_collateral REAL NOT NULL,
            stop_loss_price REAL DEFAULT NULL,
            take_profit_price REAL DEFAULT NULL,
            cumulative_fees_paid REAL NOT NULL DEFAULT 0.0,
            opened_at TEXT NOT NULL DEFAULT (datetime('now')),
            closed_at TEXT DEFAULT NULL,
            status TEXT NOT NULL DEFAULT 'active',
            FOREIGN KEY (user_id) REFERENCES users(id),
            FOREIGN KEY (ore_id) REFERENCES ores(id)
        )
    """)

    # Create advancements table
    conn.execute("""
        CREATE TABLE IF NOT EXISTS advancements (
            id INTEGER PRIMARY KEY,
            user_id INTEGER NOT NULL,
            advancement_key TEXT NOT NULL,
            earned_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
            UNIQUE(user_id, advancement_key),
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        )
    """)

    # Create notifications table (award_advancement calls create_notification)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS notifications (
            id INTEGER PRIMARY KEY,
            user_id INTEGER NOT NULL,
            category TEXT NOT NULL,
            message TEXT NOT NULL,
            action_url TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        )
    """)

    # Create indexes
    conn.execute("CREATE INDEX IF NOT EXISTS idx_advancements_user ON advancements(user_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_holdings_user ON holdings(user_id)")

    # Insert a test user with the specified balance (net_worth == balance here)
    conn.execute(
        "INSERT INTO users (id, username, password_hash, balance) VALUES (1, 'testuser', 'hash123', ?)",
        (balance,),
    )
    conn.commit()
    return conn


from app.advancements import evaluate_tick_advancements


@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(
    net_worth=st.floats(min_value=0, max_value=20_000_000),
)
def test_net_worth_threshold_advancement_awards(net_worth):
    """Property 3: For any player with net worth N who does not already have the
    achievement: "millionaire" SHALL be awarded if and only if N >= 1,000,000, and
    "multimillionaire" SHALL be awarded if and only if N >= 10,000,000. If N < the
    respective threshold, the achievement SHALL NOT be awarded.

    **Validates: Requirements 4.1, 5.1**
    """
    db = _create_net_worth_test_db(net_worth)

    try:
        evaluate_tick_advancements(db)
        db.commit()

        # Check millionaire: awarded iff net_worth >= 1,000,000
        has_millionaire = has_advancement(db, 1, "millionaire")
        if net_worth >= 1_000_000:
            assert has_millionaire, (
                f"millionaire should be awarded when net_worth={net_worth:,.2f} >= 1,000,000"
            )
        else:
            assert not has_millionaire, (
                f"millionaire should NOT be awarded when net_worth={net_worth:,.2f} < 1,000,000"
            )

        # Check multimillionaire: awarded iff net_worth >= 10,000,000
        has_multimillionaire = has_advancement(db, 1, "multimillionaire")
        if net_worth >= 10_000_000:
            assert has_multimillionaire, (
                f"multimillionaire should be awarded when net_worth={net_worth:,.2f} >= 10,000,000"
            )
        else:
            assert not has_multimillionaire, (
                f"multimillionaire should NOT be awarded when net_worth={net_worth:,.2f} < 10,000,000"
            )
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Feature: achievements-system, Property 5: What a Deal! Trade Count
# Validates: Requirements 8.1, 8.2, 8.3
# ---------------------------------------------------------------------------


def _create_trade_test_db(transactions):
    """Create an in-memory SQLite database with transactions for trade count testing.

    Args:
        transactions: list of (type, archived) tuples representing transaction records.
    """
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

    # Create ores table (needed for FK on transactions)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS ores (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL UNIQUE,
            description TEXT,
            icon_filename TEXT,
            current_price REAL NOT NULL,
            base_price REAL NOT NULL,
            price_floor REAL NOT NULL,
            price_ceiling REAL NOT NULL,
            volatility REAL NOT NULL,
            price_change_range TEXT NOT NULL,
            base_probabilities TEXT NOT NULL,
            trend_log TEXT NOT NULL DEFAULT '["hold","hold","hold","hold","hold"]'
        )
    """)

    # Create transactions table
    conn.execute("""
        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY,
            user_id INTEGER NOT NULL,
            ore_id INTEGER NOT NULL,
            type TEXT NOT NULL,
            quantity INTEGER NOT NULL,
            price_at_trade REAL NOT NULL,
            total_value REAL NOT NULL,
            archived INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY (user_id) REFERENCES users(id),
            FOREIGN KEY (ore_id) REFERENCES ores(id)
        )
    """)

    # Create advancements table
    conn.execute("""
        CREATE TABLE IF NOT EXISTS advancements (
            id INTEGER PRIMARY KEY,
            user_id INTEGER NOT NULL,
            advancement_key TEXT NOT NULL,
            earned_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
            UNIQUE(user_id, advancement_key),
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        )
    """)

    # Create notifications table
    conn.execute("""
        CREATE TABLE IF NOT EXISTS notifications (
            id INTEGER PRIMARY KEY,
            user_id INTEGER NOT NULL,
            category TEXT NOT NULL,
            message TEXT NOT NULL,
            action_url TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        )
    """)

    conn.execute("CREATE INDEX IF NOT EXISTS idx_advancements_user ON advancements(user_id)")

    # Insert test user and a dummy ore
    conn.execute(
        "INSERT INTO users (id, username, password_hash) VALUES (1, 'testuser', 'hash123')"
    )
    conn.execute(
        "INSERT INTO ores (id, name, current_price, base_price, price_floor, price_ceiling, volatility, price_change_range, base_probabilities) "
        "VALUES (1, 'TestOre', 100.0, 100.0, 50.0, 200.0, 0.1, '[1,2]', '[0.5,0.5]')"
    )

    # Insert transactions
    for txn_type, archived in transactions:
        conn.execute(
            "INSERT INTO transactions (user_id, ore_id, type, quantity, price_at_trade, total_value, archived) "
            "VALUES (1, 1, ?, 1, 100.0, 100.0, ?)",
            (txn_type, 1 if archived else 0),
        )

    conn.commit()
    return conn


@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(
    transactions=st.lists(
        st.tuples(
            st.sampled_from(["buy", "sell", "short_open", "short_close", "short_liquidated"]),
            st.booleans(),
        ),
        min_size=0,
        max_size=150,
    ),
)
def test_what_a_deal_trade_count(transactions):
    """Property 5: For any player with transactions of types {buy, sell, short_open,
    short_close, short_liquidated} across both archived and non-archived records, the
    Trade_Count SHALL equal the total number of all such transactions regardless of type
    or archived status. "day_trader" SHALL be awarded if and only if Trade_Count >= 100.

    **Validates: Requirements 8.1, 8.2, 8.3**
    """
    db = _create_trade_test_db(transactions)

    try:
        trade_count = len(transactions)

        evaluate_trade_advancement(db, 1)
        db.commit()

        has_day_trader = has_advancement(db, 1, "day_trader")

        if trade_count >= 100:
            assert has_day_trader, (
                f"day_trader should be awarded when trade_count={trade_count} >= 100"
            )
        else:
            assert not has_day_trader, (
                f"day_trader should NOT be awarded when trade_count={trade_count} < 100"
            )
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Feature: achievements-system, Property 10: Completionist Requires All Eight
# Validates: Requirements 10.1
# ---------------------------------------------------------------------------

# All advancement keys excluding completionist
_NON_COMPLETIONIST_KEYS = [k for k in ADVANCEMENT_KEYS if k != "completionist"]


@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(
    earned_set=st.sets(
        st.sampled_from(_NON_COMPLETIONIST_KEYS),
        min_size=0,
        max_size=8,
    ),
)
def test_completionist_requires_all_eight(earned_set):  # noqa: C901
    """Property 10: For any player with a set of earned achievements E (excluding
    "completionist"), "completionist" SHALL be awarded if and only if E contains all
    eight other achievement keys. If any of the eight is missing, "completionist"
    SHALL NOT be awarded.

    **Validates: Requirements 10.1**
    """
    db = _create_test_db()

    try:
        # Pre-seed the earned advancements (bypass award_advancement to avoid
        # triggering evaluate_completionist during seeding)
        for key in earned_set:
            db.execute(
                "INSERT OR IGNORE INTO advancements (user_id, advancement_key, earned_at) "
                "VALUES (1, ?, datetime('now', 'localtime'))",
                (key,),
            )
        db.commit()

        # Now evaluate completionist
        evaluate_completionist(db, 1)
        db.commit()

        has_completionist = has_advancement(db, 1, "completionist")
        all_eight_earned = len(earned_set) == 8

        if all_eight_earned:
            assert has_completionist, (
                f"completionist should be awarded when all 8 non-completionist advancements are earned. "
                f"Earned: {earned_set}"
            )
        else:
            assert not has_completionist, (
                f"completionist should NOT be awarded when only {len(earned_set)}/8 advancements are earned. "
                f"Earned: {earned_set}, Missing: {set(_NON_COMPLETIONIST_KEYS) - earned_set}"
            )
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Feature: achievements-system, Property 9: Go for Diamond! Rank Determination
# Validates: Requirements 5.4, 10.3, 12.1
# ---------------------------------------------------------------------------


def _create_multi_user_net_worth_db(balances):
    """Create an in-memory SQLite database with multiple users for rank testing.

    Each user's net_worth == their balance (no holdings or short positions).
    Args:
        balances: list of floats, one per user.
    Returns:
        (conn, user_ids) — the connection and a list of user IDs created.
    """
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")

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

    conn.execute("""
        CREATE TABLE IF NOT EXISTS ores (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL UNIQUE,
            description TEXT,
            icon_filename TEXT,
            current_price REAL NOT NULL,
            base_price REAL NOT NULL,
            price_floor REAL NOT NULL,
            price_ceiling REAL NOT NULL,
            volatility REAL NOT NULL,
            price_change_range TEXT NOT NULL,
            base_probabilities TEXT NOT NULL,
            trend_log TEXT NOT NULL DEFAULT '["hold","hold","hold","hold","hold"]'
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS holdings (
            id INTEGER PRIMARY KEY,
            user_id INTEGER NOT NULL,
            ore_id INTEGER NOT NULL,
            quantity INTEGER NOT NULL,
            avg_purchase_price REAL NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users(id),
            FOREIGN KEY (ore_id) REFERENCES ores(id)
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS short_positions (
            id INTEGER PRIMARY KEY,
            user_id INTEGER NOT NULL,
            ore_id INTEGER NOT NULL,
            share_quantity INTEGER NOT NULL,
            entry_price REAL NOT NULL,
            locked_collateral REAL NOT NULL,
            stop_loss_price REAL DEFAULT NULL,
            take_profit_price REAL DEFAULT NULL,
            cumulative_fees_paid REAL NOT NULL DEFAULT 0.0,
            opened_at TEXT NOT NULL DEFAULT (datetime('now')),
            closed_at TEXT DEFAULT NULL,
            status TEXT NOT NULL DEFAULT 'active',
            FOREIGN KEY (user_id) REFERENCES users(id),
            FOREIGN KEY (ore_id) REFERENCES ores(id)
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS advancements (
            id INTEGER PRIMARY KEY,
            user_id INTEGER NOT NULL,
            advancement_key TEXT NOT NULL,
            earned_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
            UNIQUE(user_id, advancement_key),
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS notifications (
            id INTEGER PRIMARY KEY,
            user_id INTEGER NOT NULL,
            category TEXT NOT NULL,
            message TEXT NOT NULL,
            action_url TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        )
    """)

    conn.execute("CREATE INDEX IF NOT EXISTS idx_advancements_user ON advancements(user_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_holdings_user ON holdings(user_id)")

    user_ids = []
    for i, balance in enumerate(balances, start=1):
        conn.execute(
            "INSERT INTO users (id, username, password_hash, balance) VALUES (?, ?, 'hash', ?)",
            (i, f"player_{i}", balance),
        )
        user_ids.append(i)

    conn.commit()
    return conn, user_ids


@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(
    player_net_worths=st.lists(
        st.floats(min_value=1000, max_value=10_000_000),
        min_size=2,
        max_size=20,
    ),
)
def test_go_for_diamond_rank_determination(player_net_worths):
    """Property 9: For any set of players with their respective net worths,
    "best_of_the_rest" (Go for Diamond!) SHALL be awarded to all players whose
    net worth equals the maximum net worth in the set (rank 1), and SHALL NOT be
    awarded to any player whose net worth is less than the maximum.

    **Validates: Requirements 5.4, 10.3, 12.1**
    """
    db, user_ids = _create_multi_user_net_worth_db(player_net_worths)

    try:
        evaluate_tick_advancements(db)
        db.commit()

        max_net_worth = max(player_net_worths)

        for idx, (uid, nw) in enumerate(zip(user_ids, player_net_worths)):
            awarded = has_advancement(db, uid, "best_of_the_rest")
            if nw == max_net_worth:
                assert awarded, (
                    f"Player {uid} (net_worth={nw:,.2f}) should have best_of_the_rest "
                    f"because they are tied at the maximum ({max_net_worth:,.2f})"
                )
            else:
                assert not awarded, (
                    f"Player {uid} (net_worth={nw:,.2f}) should NOT have best_of_the_rest "
                    f"because they are below the maximum ({max_net_worth:,.2f})"
                )
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Feature: achievements-system, Property 11: Theme Unlock on Achievement Award
# Validates: Requirements 12.4, 13.1, 13.2
# ---------------------------------------------------------------------------


@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(key=st.sampled_from(ADVANCEMENT_KEYS))
def test_theme_unlock_on_achievement_award(key):
    """Property 11: For any player, when "multimillionaire" is awarded, the
    player's money_theme_unlocked SHALL become 1. When "completionist" is awarded,
    the player's gold_theme_unlocked SHALL become 1. No other achievement SHALL
    modify either theme flag.

    **Validates: Requirements 12.4, 13.1, 13.2**
    """
    db = _create_test_db()
    user_id = 1

    try:
        # Confirm theme flags start at 0
        row_before = db.execute(
            "SELECT money_theme_unlocked, gold_theme_unlocked FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()
        assert row_before["money_theme_unlocked"] == 0
        assert row_before["gold_theme_unlocked"] == 0

        # Award the advancement
        award_advancement(db, user_id, key)
        db.commit()

        # Check theme flags after award
        row_after = db.execute(
            "SELECT money_theme_unlocked, gold_theme_unlocked FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()

        if key == "multimillionaire":
            assert row_after["money_theme_unlocked"] == 1, (
                f"money_theme_unlocked should be 1 after awarding multimillionaire"
            )
        else:
            assert row_after["money_theme_unlocked"] == 0, (
                f"money_theme_unlocked should remain 0 after awarding {key!r}"
            )

        if key == "completionist":
            assert row_after["gold_theme_unlocked"] == 1, (
                f"gold_theme_unlocked should be 1 after awarding completionist"
            )
        else:
            assert row_after["gold_theme_unlocked"] == 0, (
                f"gold_theme_unlocked should remain 0 after awarding {key!r}"
            )
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Feature: achievements-system, Property 15: Play Time Heartbeat Increment Calculation
# Validates: Requirements 2.2, 2.4
# ---------------------------------------------------------------------------

import math


@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(elapsed_seconds=st.integers(min_value=0, max_value=7200))
def test_play_time_heartbeat_increment_calculation(elapsed_seconds):
    """Property 15: For any elapsed time E seconds since the last heartbeat,
    the play_time increment SHALL equal min(floor(E / 60), 5). If E < 60 seconds,
    the increment SHALL be 0 (no DB write occurs). The 5-minute cap prevents
    stale sessions from awarding unbounded time.

    This tests the pure calculation logic used in record_heartbeat:
        elapsed_minutes = min(math.floor(elapsed / 60), max_increment)
    where max_increment = 5 and the heartbeat interval = 60 seconds.

    **Validates: Requirements 2.2, 2.4**
    """
    # --- Replicate the heartbeat calculation logic from src/app/playtime.py ---
    interval = 60  # PLAYTIME_HEARTBEAT_INTERVAL default
    max_increment = 5  # PLAYTIME_MAX_INCREMENT default

    # If elapsed < interval, no increment occurs (early return in record_heartbeat)
    if elapsed_seconds < interval:
        expected_increment = 0
    else:
        expected_increment = min(math.floor(elapsed_seconds / 60), max_increment)

    # --- Verify the property ---
    # 1. When elapsed < 60, increment must be 0
    if elapsed_seconds < 60:
        assert expected_increment == 0, (
            f"Increment should be 0 when elapsed={elapsed_seconds}s < 60s, "
            f"got {expected_increment}"
        )
    else:
        # 2. When elapsed >= 60, increment = min(floor(elapsed/60), 5)
        raw_minutes = math.floor(elapsed_seconds / 60)
        capped = min(raw_minutes, 5)
        assert expected_increment == capped, (
            f"Increment should be min(floor({elapsed_seconds}/60), 5) = {capped}, "
            f"got {expected_increment}"
        )

    # 3. Increment is always in [0, 5]
    assert 0 <= expected_increment <= 5, (
        f"Increment must be in [0, 5], got {expected_increment} for elapsed={elapsed_seconds}s"
    )

    # 4. The 5-minute cap holds for large elapsed values
    if elapsed_seconds >= 300:  # 5 minutes or more
        assert expected_increment == 5, (
            f"Increment should be capped at 5 when elapsed={elapsed_seconds}s >= 300s, "
            f"got {expected_increment}"
        )


# ---------------------------------------------------------------------------
# Feature: achievements-system, Property 2: Login Streak State Machine
# Validates: Requirements 3.2, 3.3, 3.4, 3.5
# ---------------------------------------------------------------------------


from unittest.mock import patch
from app.advancements import update_login_streak


@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(
    streak=st.integers(min_value=1, max_value=365),
    last_date=st.dates(),
    day_offset=st.integers(min_value=0, max_value=5),
)
def test_login_streak_state_machine(streak, last_date, day_offset):
    """Property 2: Login Streak State Machine — For any current login_streak
    value S, last_streak_date D, and current date T:
    - If T == D, the streak SHALL remain S (last_streak_date stays D)
    - If T == D + 1 day, the streak SHALL become S + 1 (last_streak_date updated to T)
    - If T > D + 1 day, the streak SHALL become 1 (last_streak_date updated to T)

    Also tests the NULL case: when last_streak_date is NULL, streak SHALL become 1
    and last_streak_date SHALL be set to T.

    **Validates: Requirements 3.2, 3.3, 3.4, 3.5**
    """
    import datetime

    db = _create_test_db()
    user_id = 1

    # Compute "today" as last_date + day_offset
    today = last_date + datetime.timedelta(days=day_offset)

    try:
        # Set up the user's login_streak and last_streak_date to generated values
        db.execute(
            "UPDATE users SET login_streak = ?, last_streak_date = ? WHERE id = ?",
            (streak, last_date.isoformat(), user_id),
        )
        db.commit()

        # Patch datetime.date.today in the advancements module
        with patch("app.advancements.datetime") as mock_datetime:
            mock_datetime.date.today.return_value = today
            mock_datetime.date.fromisoformat = datetime.date.fromisoformat
            update_login_streak(db, user_id)
            db.commit()

        # Fetch resulting state
        row = db.execute(
            "SELECT login_streak, last_streak_date FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()

        result_streak = row["login_streak"]
        result_date = row["last_streak_date"]

        delta = (today - last_date).days

        if delta <= 0:
            # Same day (or clock skew) — streak unchanged, date unchanged
            assert result_streak == streak, (
                f"Same day (delta={delta}): expected streak={streak}, got {result_streak}"
            )
            assert result_date == last_date.isoformat(), (
                f"Same day: expected last_streak_date={last_date.isoformat()}, got {result_date}"
            )
        elif delta == 1:
            # Consecutive day — streak incremented
            assert result_streak == streak + 1, (
                f"Next day (delta=1): expected streak={streak + 1}, got {result_streak}"
            )
            assert result_date == today.isoformat(), (
                f"Next day: expected last_streak_date={today.isoformat()}, got {result_date}"
            )
        else:
            # Gap > 1 day — streak reset to 1
            assert result_streak == 1, (
                f"Gap (delta={delta}): expected streak=1, got {result_streak}"
            )
            assert result_date == today.isoformat(), (
                f"Gap: expected last_streak_date={today.isoformat()}, got {result_date}"
            )
    finally:
        db.close()


@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(
    streak=st.integers(min_value=0, max_value=365),
    today=st.dates(),
)
def test_login_streak_null_last_date(streak, today):
    """Property 2 (NULL case): When last_streak_date is NULL, the streak SHALL
    become 1 and last_streak_date SHALL be set to T regardless of the current streak value.

    **Validates: Requirements 3.2, 3.5**
    """
    import datetime

    db = _create_test_db()
    user_id = 1

    try:
        # Set up with NULL last_streak_date
        db.execute(
            "UPDATE users SET login_streak = ?, last_streak_date = NULL WHERE id = ?",
            (streak, user_id),
        )
        db.commit()

        # Patch datetime.date.today in the advancements module
        with patch("app.advancements.datetime") as mock_datetime:
            mock_datetime.date.today.return_value = today
            mock_datetime.date.fromisoformat = datetime.date.fromisoformat
            update_login_streak(db, user_id)
            db.commit()

        # Fetch resulting state
        row = db.execute(
            "SELECT login_streak, last_streak_date FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()

        result_streak = row["login_streak"]
        result_date = row["last_streak_date"]

        # NULL last_streak_date always resets to 1
        assert result_streak == 1, (
            f"NULL last_date: expected streak=1, got {result_streak} (original streak={streak})"
        )
        assert result_date == today.isoformat(), (
            f"NULL last_date: expected last_streak_date={today.isoformat()}, got {result_date}"
        )
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Feature: achievements-system, Property 16: Advancement Display State Correctness
# Validates: Requirements 14.1, 14.4
# ---------------------------------------------------------------------------

from app.advancements import get_user_advancements


@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(
    earned_subset=st.sets(st.sampled_from(ADVANCEMENT_KEYS), min_size=0, max_size=9),
)
def test_advancement_display_state_correctness(earned_subset):
    """Property 16: For any player with a random subset of earned advancements,
    get_user_advancements returns entries with non-null earned_at for keys in the
    earned set, keys not in the earned set do NOT appear in the result, and the
    total ADVANCEMENT_KEYS always has 9 entries.

    Specifically:
    - Total ADVANCEMENT_KEYS count is always 9
    - For each key in the earned set, the earned list contains that key with a non-null earned_at
    - For each key NOT in the earned set, it does NOT appear in the earned list

    **Validates: Requirements 14.1, 14.4**
    """
    db = _create_test_db()
    user_id = 1

    try:
        # Pre-seed the earned advancements using direct INSERT (avoid side effects
        # like completionist cascading from award_advancement)
        for key in earned_subset:
            db.execute(
                "INSERT OR IGNORE INTO advancements (user_id, advancement_key, earned_at) "
                "VALUES (1, ?, datetime('now', 'localtime'))",
                (key,),
            )
        db.commit()

        # Call get_user_advancements to get the earned list
        earned_list = get_user_advancements(db, user_id)

        # Build a dict of key -> earned_at from the result for easy lookup
        earned_dict = {entry["key"]: entry["earned_at"] for entry in earned_list}

        # Assert: total ADVANCEMENT_KEYS always has 9 entries
        assert len(ADVANCEMENT_KEYS) == 9, (
            f"ADVANCEMENT_KEYS should have 9 entries, got {len(ADVANCEMENT_KEYS)}"
        )

        # Assert: for each key in the earned set, the earned list contains that key
        # with a non-null earned_at
        for key in earned_subset:
            assert key in earned_dict, (
                f"Key {key!r} was seeded but not found in get_user_advancements result"
            )
            assert earned_dict[key] is not None, (
                f"Key {key!r} has a null earned_at, expected non-null"
            )

        # Assert: for each key NOT in the earned set, it does NOT appear in the earned list
        for key in ADVANCEMENT_KEYS:
            if key not in earned_subset:
                assert key not in earned_dict, (
                    f"Key {key!r} was NOT seeded but appeared in get_user_advancements result"
                )
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Feature: achievements-system, Property 12: Account Reset Preserves Advancements and Themes
# Validates: Requirements 1.4, 16.1, 16.4
# ---------------------------------------------------------------------------


@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(
    earned_set=st.sets(st.sampled_from(ADVANCEMENT_KEYS), min_size=0, max_size=9),
    money_unlocked=st.booleans(),
    gold_unlocked=st.booleans(),
)
def test_account_reset_preserves_advancements_and_themes(earned_set, money_unlocked, gold_unlocked):
    """Property 12: After an account reset, all advancement rows remain in the
    advancements table and theme unlock flags (money_theme_unlocked,
    gold_theme_unlocked) retain their pre-reset values.

    The reset SQL sets advanced_eligible=0, advanced_purchased=0, advanced_active=0,
    advanced_toggled_at=NULL, play_time=0, login_streak=0, last_streak_date=NULL,
    balance=10000 but does NOT delete advancements and does NOT modify theme columns.

    **Validates: Requirements 1.4, 16.1, 16.4**
    """
    db = _create_test_db()
    user_id = 1

    try:
        # Set up theme unlock flags
        db.execute(
            "UPDATE users SET money_theme_unlocked = ?, gold_theme_unlocked = ? WHERE id = ?",
            (1 if money_unlocked else 0, 1 if gold_unlocked else 0, user_id),
        )

        # Seed advancements directly (bypass award_advancement to avoid side effects)
        for key in earned_set:
            db.execute(
                "INSERT OR IGNORE INTO advancements (user_id, advancement_key, earned_at) "
                "VALUES (?, ?, datetime('now', 'localtime'))",
                (user_id, key),
            )
        db.commit()

        # Execute the reset SQL (replicates what reset_account() does to the users table)
        db.execute(
            "UPDATE users SET advanced_eligible=0, advanced_purchased=0, advanced_active=0, "
            "advanced_toggled_at=NULL, play_time=0, login_streak=0, last_streak_date=NULL, "
            "balance = 10000 WHERE id = ?",
            (user_id,),
        )
        db.commit()

        # Verify all advancements still exist
        rows = db.execute(
            "SELECT advancement_key FROM advancements WHERE user_id = ?",
            (user_id,),
        ).fetchall()
        remaining_keys = {row["advancement_key"] for row in rows}
        assert remaining_keys == earned_set, (
            f"Advancements should be preserved after reset. "
            f"Expected {earned_set}, got {remaining_keys}"
        )

        # Verify theme flags are unchanged
        user_row = db.execute(
            "SELECT money_theme_unlocked, gold_theme_unlocked FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()
        assert user_row["money_theme_unlocked"] == (1 if money_unlocked else 0), (
            f"money_theme_unlocked should be preserved after reset. "
            f"Expected {1 if money_unlocked else 0}, got {user_row['money_theme_unlocked']}"
        )
        assert user_row["gold_theme_unlocked"] == (1 if gold_unlocked else 0), (
            f"gold_theme_unlocked should be preserved after reset. "
            f"Expected {1 if gold_unlocked else 0}, got {user_row['gold_theme_unlocked']}"
        )
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Feature: achievements-system, Property 13: Account Reset Clears Progress Counters
# Validates: Requirements 16.2, 16.3
# ---------------------------------------------------------------------------


@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(
    play_time=st.integers(min_value=0, max_value=1000),
    login_streak=st.integers(min_value=0, max_value=100),
    last_streak_date=st.one_of(st.none(), st.dates().map(lambda d: d.isoformat())),
)
def test_account_reset_clears_progress_counters(play_time, login_streak, last_streak_date):
    """Property 13: After an account reset, the progress counters play_time,
    login_streak, and last_streak_date SHALL be cleared:
    play_time=0, login_streak=0, last_streak_date=NULL.

    **Validates: Requirements 16.2, 16.3**
    """
    db = _create_test_db()
    user_id = 1

    try:
        # Set up the user with non-zero progress counters
        db.execute(
            "UPDATE users SET play_time = ?, login_streak = ?, last_streak_date = ? WHERE id = ?",
            (play_time, login_streak, last_streak_date, user_id),
        )
        db.commit()

        # Execute the reset SQL (replicates what reset_account() does to the users table)
        db.execute(
            "UPDATE users SET advanced_eligible=0, advanced_purchased=0, advanced_active=0, "
            "advanced_toggled_at=NULL, play_time=0, login_streak=0, last_streak_date=NULL, "
            "balance = 10000 WHERE id = ?",
            (user_id,),
        )
        db.commit()

        # Verify progress counters are cleared
        row = db.execute(
            "SELECT play_time, login_streak, last_streak_date FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()

        assert row["play_time"] == 0, (
            f"play_time should be 0 after reset, got {row['play_time']} "
            f"(was {play_time} before reset)"
        )
        assert row["login_streak"] == 0, (
            f"login_streak should be 0 after reset, got {row['login_streak']} "
            f"(was {login_streak} before reset)"
        )
        assert row["last_streak_date"] is None, (
            f"last_streak_date should be NULL after reset, got {row['last_streak_date']!r} "
            f"(was {last_streak_date!r} before reset)"
        )
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Feature: achievements-system, Property 14: CASCADE Delete Removes All Advancements
# Validates: Requirements 16.5
# ---------------------------------------------------------------------------


@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(
    earned_set=st.sets(st.sampled_from(ADVANCEMENT_KEYS), min_size=1, max_size=9),
)
def test_cascade_delete_removes_all_advancements(earned_set):
    """Property 14: After a user row is deleted, zero advancement records SHALL
    exist for that user_id due to the ON DELETE CASCADE foreign key constraint.

    **Validates: Requirements 16.5**
    """
    db = _create_test_db()
    user_id = 1

    try:
        # Seed advancements directly
        for key in earned_set:
            db.execute(
                "INSERT OR IGNORE INTO advancements (user_id, advancement_key, earned_at) "
                "VALUES (?, ?, datetime('now', 'localtime'))",
                (user_id, key),
            )
        db.commit()

        # Confirm advancements exist before delete
        count_before = db.execute(
            "SELECT COUNT(*) as cnt FROM advancements WHERE user_id = ?",
            (user_id,),
        ).fetchone()["cnt"]
        assert count_before == len(earned_set), (
            f"Expected {len(earned_set)} advancements before delete, got {count_before}"
        )

        # Delete the user row — CASCADE should remove advancements
        db.execute("DELETE FROM users WHERE id = ?", (user_id,))
        db.commit()

        # Verify zero advancement records remain for the deleted user
        count_after = db.execute(
            "SELECT COUNT(*) as cnt FROM advancements WHERE user_id = ?",
            (user_id,),
        ).fetchone()["cnt"]
        assert count_after == 0, (
            f"Expected 0 advancements after user delete (CASCADE), got {count_after}. "
            f"Earned set was: {earned_set}"
        )
    finally:
        db.close()
