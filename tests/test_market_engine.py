"""Tests for the market engine.

Covers price updates via process_tick, floor/ceiling clamping, trend log
structure, bot creation via ensure_bots_exist, bot transactions, price
history recording, and idempotency of bot creation.
"""

import json
import random

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st

pytestmark = pytest.mark.market_engine


class TestMarketEngine:
    """Tests for market engine algorithm and bot logic."""

    def test_process_tick_changes_at_least_one_price(self, app):
        """TC: process_tick with fixed seed changes at least one ore price."""
        with app.app_context():
            from app.database import get_db
            from app.market.bots import ensure_bots_exist
            from app.market.algorithm import process_tick

            db = get_db()
            ensure_bots_exist(db, app.config['DEFAULT_BALANCE'])

            # Record prices before tick
            ores_before = db.execute("SELECT id, current_price FROM ores").fetchall()
            prices_before = {row['id']: row['current_price'] for row in ores_before}

            # Use a fixed seed for determinism
            random.seed(42)
            process_tick(db)

            # Record prices after tick
            ores_after = db.execute("SELECT id, current_price FROM ores").fetchall()
            prices_after = {row['id']: row['current_price'] for row in ores_after}

            # At least one ore should have changed price
            changed = any(
                prices_before[ore_id] != prices_after[ore_id]
                for ore_id in prices_before
            )
            assert changed, "Expected at least one ore price to change after process_tick"

    def test_all_prices_within_floor_ceiling_after_tick(self, app):
        """TC: all prices remain within floor/ceiling bounds after tick."""
        with app.app_context():
            from app.database import get_db
            from app.market.bots import ensure_bots_exist
            from app.market.algorithm import process_tick

            db = get_db()
            ensure_bots_exist(db, app.config['DEFAULT_BALANCE'])

            random.seed(99)
            process_tick(db)

            ores = db.execute(
                "SELECT name, current_price, price_floor, price_ceiling FROM ores"
            ).fetchall()

            for ore in ores:
                assert ore['current_price'] >= ore['price_floor'], (
                    f"{ore['name']}: price {ore['current_price']} below floor {ore['price_floor']}"
                )
                assert ore['current_price'] <= ore['price_ceiling'], (
                    f"{ore['name']}: price {ore['current_price']} above ceiling {ore['price_ceiling']}"
                )

    def test_trend_log_structure_after_tick(self, app):
        """TC: trend_log is JSON array of exactly 5 entries ('rise', 'hold', or 'fall')."""
        with app.app_context():
            from app.database import get_db
            from app.market.bots import ensure_bots_exist
            from app.market.algorithm import process_tick

            db = get_db()
            ensure_bots_exist(db, app.config['DEFAULT_BALANCE'])

            random.seed(7)
            process_tick(db)

            ores = db.execute("SELECT name, trend_log FROM ores").fetchall()
            valid_entries = {'rise', 'hold', 'fall'}

            for ore in ores:
                trend_log = json.loads(ore['trend_log'])
                assert isinstance(trend_log, list), (
                    f"{ore['name']}: trend_log is not a list"
                )
                assert len(trend_log) == 5, (
                    f"{ore['name']}: trend_log has {len(trend_log)} entries, expected 5"
                )
                for entry in trend_log:
                    assert entry in valid_entries, (
                        f"{ore['name']}: invalid trend_log entry '{entry}'"
                    )

    def test_ensure_bots_exist_creates_nine_bots(self, app):
        """TC: ensure_bots_exist creates exactly 9 bot accounts with 'BOT_NO_LOGIN' password hash."""
        with app.app_context():
            from app.database import get_db
            from app.market.bots import ensure_bots_exist, BOT_NAMES

            db = get_db()

            # Verify no bots exist initially
            bot_count_before = db.execute(
                "SELECT COUNT(*) FROM users WHERE password_hash = 'BOT_NO_LOGIN'"
            ).fetchone()[0]
            assert bot_count_before == 0

            ensure_bots_exist(db, app.config['DEFAULT_BALANCE'])

            # Verify exactly 9 bots created
            bots = db.execute(
                "SELECT username, password_hash, balance FROM users WHERE password_hash = 'BOT_NO_LOGIN'"
            ).fetchall()
            assert len(bots) == 9

            # Verify each bot has the correct attributes
            bot_usernames = {row['username'] for row in bots}
            assert bot_usernames == set(BOT_NAMES)

            for bot in bots:
                assert bot['password_hash'] == 'BOT_NO_LOGIN'
                assert bot['balance'] == app.config['DEFAULT_BALANCE']

    def test_process_tick_bot_trades_insert_transaction(self, app):
        """TC: process_tick with seed producing bot trades inserts transaction for bot user."""
        with app.app_context():
            from app.database import get_db
            from app.market.bots import ensure_bots_exist, BOT_NAMES
            from app.market.algorithm import process_tick

            db = get_db()
            ensure_bots_exist(db, app.config['DEFAULT_BALANCE'])

            # Count transactions before tick
            tx_count_before = db.execute(
                "SELECT COUNT(*) FROM transactions"
            ).fetchone()[0]

            # Use a seed that will produce bot trades (bots have 50/20/30 or
            # 20/30/50 weights for buy/hold/sell, so most seeds produce trades)
            random.seed(42)
            process_tick(db)

            # Get bot user IDs
            bot_ids = db.execute(
                "SELECT id FROM users WHERE username IN ({})".format(
                    ','.join('?' * len(BOT_NAMES))
                ),
                BOT_NAMES
            ).fetchall()
            bot_id_set = {row['id'] for row in bot_ids}

            # Check that at least one transaction was inserted for a bot user
            bot_transactions = db.execute(
                "SELECT * FROM transactions WHERE user_id IN ({})".format(
                    ','.join('?' * len(bot_id_set))
                ),
                list(bot_id_set)
            ).fetchall()

            assert len(bot_transactions) > 0, (
                "Expected at least one bot transaction after process_tick"
            )

    def test_price_history_one_row_per_ore_per_tick(self, app):
        """TC: exactly one price_history row per ore inserted per tick with correct fields."""
        with app.app_context():
            from app.database import get_db
            from app.market.bots import ensure_bots_exist
            from app.market.algorithm import process_tick

            db = get_db()
            ensure_bots_exist(db, app.config['DEFAULT_BALANCE'])

            # Verify no price history exists initially
            history_before = db.execute(
                "SELECT COUNT(*) FROM price_history"
            ).fetchone()[0]
            assert history_before == 0

            random.seed(123)
            process_tick(db)

            # Get all ores and their current prices after tick
            ores = db.execute("SELECT id, current_price FROM ores").fetchall()
            ore_count = len(ores)
            assert ore_count == 9

            # Verify exactly one price_history row per ore
            history_rows = db.execute(
                "SELECT ore_id, price, movement, created_at FROM price_history"
            ).fetchall()
            assert len(history_rows) == ore_count, (
                f"Expected {ore_count} price_history rows, got {len(history_rows)}"
            )

            valid_movements = {'rise', 'hold', 'fall'}
            ore_prices = {row['id']: row['current_price'] for row in ores}

            for row in history_rows:
                # Price matches the ore's updated current_price
                assert row['price'] == ore_prices[row['ore_id']], (
                    f"Ore {row['ore_id']}: history price {row['price']} != "
                    f"current_price {ore_prices[row['ore_id']]}"
                )
                # Movement is valid
                assert row['movement'] in valid_movements, (
                    f"Ore {row['ore_id']}: invalid movement '{row['movement']}'"
                )
                # created_at is non-empty (ISO 8601 format)
                assert row['created_at'] and len(row['created_at']) > 0, (
                    f"Ore {row['ore_id']}: created_at is empty"
                )

    def test_ensure_bots_exist_idempotent(self, app):
        """TC: ensure_bots_exist is idempotent (no duplicates on repeat call)."""
        with app.app_context():
            from app.database import get_db
            from app.market.bots import ensure_bots_exist

            db = get_db()

            # Call ensure_bots_exist twice
            ensure_bots_exist(db, app.config['DEFAULT_BALANCE'])
            ensure_bots_exist(db, app.config['DEFAULT_BALANCE'])

            # Verify still exactly 9 bot accounts
            bot_count = db.execute(
                "SELECT COUNT(*) FROM users WHERE password_hash = 'BOT_NO_LOGIN'"
            ).fetchone()[0]
            assert bot_count == 9, (
                f"Expected 9 bot accounts after repeated calls, got {bot_count}"
            )


class TestMarketEngineProperties:
    """Property-based tests for market engine invariants using Hypothesis."""

    # Feature: orex-test-suite, Property 7: Price clamping invariant
    @settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
    @given(seed=st.integers(min_value=0, max_value=10000))
    def test_price_clamping_invariant(self, seed, app):
        """**Validates: Requirements 9.2**

        For any random seed, after process_tick completes, every ore's
        current_price satisfies price_floor <= current_price <= price_ceiling.
        """
        with app.app_context():
            from app.database import get_db
            from app.market.bots import ensure_bots_exist
            from app.market.algorithm import process_tick

            db = get_db()
            ensure_bots_exist(db, app.config['DEFAULT_BALANCE'])

            # Reset ore prices back to base prices before each iteration
            ores_initial = db.execute("SELECT id, base_price FROM ores").fetchall()
            for ore in ores_initial:
                db.execute(
                    "UPDATE ores SET current_price = ? WHERE id = ?",
                    (ore['base_price'], ore['id'])
                )
            db.execute("DELETE FROM price_history")
            db.commit()

            random.seed(seed)
            process_tick(db)

            ores = db.execute(
                "SELECT name, current_price, price_floor, price_ceiling FROM ores"
            ).fetchall()

            for ore in ores:
                assert ore['price_floor'] <= ore['current_price'] <= ore['price_ceiling'], (
                    f"{ore['name']}: price {ore['current_price']} not in "
                    f"[{ore['price_floor']}, {ore['price_ceiling']}]"
                )

    # Feature: orex-test-suite, Property 8: Trend log structure invariant
    @settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
    @given(seed=st.integers(min_value=0, max_value=10000))
    def test_trend_log_structure_invariant(self, seed, app):
        """Every ore's trend_log is a JSON array of exactly 5 elements from {"rise", "hold", "fall"}.

        **Validates: Requirements 9.3**
        """
        with app.app_context():
            from app.database import get_db
            from app.market.bots import ensure_bots_exist
            from app.market.algorithm import process_tick

            db = get_db()

            # Reset ore state before each iteration
            db.execute(
                "UPDATE ores SET current_price = base_price, "
                "trend_log = '[\"hold\",\"hold\",\"hold\",\"hold\",\"hold\"]'"
            )
            db.execute("DELETE FROM price_history")
            db.commit()

            ensure_bots_exist(db, app.config['DEFAULT_BALANCE'])

            random.seed(seed)
            process_tick(db)

            ores = db.execute("SELECT name, trend_log FROM ores").fetchall()
            valid_entries = {'rise', 'hold', 'fall'}

            for ore in ores:
                trend_log = json.loads(ore['trend_log'])
                assert isinstance(trend_log, list), (
                    f"{ore['name']}: trend_log is not a list"
                )
                assert len(trend_log) == 5, (
                    f"{ore['name']}: trend_log has {len(trend_log)} entries, expected 5"
                )
                for entry in trend_log:
                    assert entry in valid_entries, (
                        f"{ore['name']}: invalid trend_log entry '{entry}'"
                    )

    # Feature: orex-test-suite, Property 9: Price history recording invariant
    @settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
    @given(seed=st.integers(min_value=0, max_value=10000))
    def test_price_history_recording_invariant(self, seed, app):
        """Exactly one new price_history row per ore per tick with correct price, movement, and timestamp.

        **Validates: Requirements 9.6**
        """
        with app.app_context():
            from app.database import get_db
            from app.market.bots import ensure_bots_exist
            from app.market.algorithm import process_tick

            db = get_db()

            # Reset state: clear price_history and reset ore prices before each iteration
            db.execute("DELETE FROM price_history")
            db.execute(
                "UPDATE ores SET current_price = base_price, "
                "trend_log = '[\"hold\",\"hold\",\"hold\",\"hold\",\"hold\"]'"
            )
            db.commit()

            ensure_bots_exist(db, app.config['DEFAULT_BALANCE'])

            random.seed(seed)
            process_tick(db)

            # After tick: verify exactly 9 new rows (one per ore)
            history_rows = db.execute(
                "SELECT ph.ore_id, ph.price, ph.movement, ph.created_at "
                "FROM price_history ph"
            ).fetchall()
            assert len(history_rows) == 9, (
                f"Expected 9 price_history rows, got {len(history_rows)}"
            )

            # Get updated ore prices after tick
            ores = db.execute("SELECT id, current_price FROM ores").fetchall()
            ore_prices = {row['id']: row['current_price'] for row in ores}

            valid_movements = {'rise', 'hold', 'fall'}

            for row in history_rows:
                # Price matches the ore's updated current_price
                assert row['price'] == ore_prices[row['ore_id']], (
                    f"Ore {row['ore_id']}: history price {row['price']} != "
                    f"current_price {ore_prices[row['ore_id']]}"
                )
                # Movement is valid
                assert row['movement'] in valid_movements, (
                    f"Ore {row['ore_id']}: invalid movement '{row['movement']}'"
                )
                # created_at is non-empty ISO 8601 value
                assert row['created_at'] and len(row['created_at']) > 0, (
                    f"Ore {row['ore_id']}: created_at is empty"
                )
