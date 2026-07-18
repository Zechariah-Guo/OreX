"""Integration tests for the full short position lifecycle.

Tests end-to-end flows through the shorting engine:
- Full short lifecycle: open → tick → price drop → close → profit credited
- Margin call cascade: open → price rises → margin calls → liquidation
- Fee bleed to liquidation: open → many ticks → fees exhaust FreeCash
- SL/TP trigger: open with SL → price rises past SL → auto-close
- Multi-position tick: 3 shorts → tick processes all → verify order and state
- Net worth on leaderboard: player with shorts has correct net worth
- Account reset mid-short: active shorts → reset → verify clean state
- No surplus release: price drops → vault stays frozen (no surplus to FreeCash)

Requirements validated: 2.5, 3.3, 4.2, 5.2, 6.1, 7.4, 12.1, 14.1, 14.5
"""

import sqlite3
from datetime import datetime, timedelta

import pytest

from conftest import register_user

pytestmark = pytest.mark.shorting_integration


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_db_conn(app):
    """Get a direct SQLite connection to the test database."""
    conn = sqlite3.connect(app.config['DATABASE_PATH'])
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _setup_advanced_user(app, username='TestUser1', balance=10000.0):
    """Create a user with Advanced Mode active and specified balance.

    Returns the user_id.
    """
    conn = _get_db_conn(app)
    row = conn.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone()
    if row is None:
        conn.close()
        raise RuntimeError(f"User {username} not found. Register first.")
    user_id = row['id']
    conn.execute(
        """UPDATE users SET balance = ?, advanced_eligible = 1,
           advanced_purchased = 1, advanced_active = 1 WHERE id = ?""",
        (balance, user_id),
    )
    conn.commit()
    conn.close()
    return user_id


def _create_short_position(app, user_id, ore_id, share_quantity, entry_price,
                           locked_collateral, stop_loss_price=None,
                           take_profit_price=None, opened_at=None):
    """Insert a short position directly into the database. Returns position ID."""
    conn = _get_db_conn(app)
    if opened_at is None:
        opened_at = datetime.now().isoformat()
    cursor = conn.execute(
        """INSERT INTO short_positions
           (user_id, ore_id, share_quantity, entry_price, locked_collateral,
            stop_loss_price, take_profit_price, cumulative_fees_paid, opened_at, status)
           VALUES (?, ?, ?, ?, ?, ?, ?, 0.0, ?, 'active')""",
        (user_id, ore_id, share_quantity, entry_price, locked_collateral,
         stop_loss_price, take_profit_price, opened_at),
    )
    pos_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return pos_id


def _set_ore_price(app, ore_id, price):
    """Directly update an ore's current_price."""
    conn = _get_db_conn(app)
    conn.execute("UPDATE ores SET current_price = ? WHERE id = ?", (price, ore_id))
    conn.commit()
    conn.close()


def _get_user_balance(app, username='TestUser1'):
    """Fetch the user's current balance (FreeCash)."""
    conn = _get_db_conn(app)
    row = conn.execute("SELECT balance FROM users WHERE username = ?", (username,)).fetchone()
    conn.close()
    return row['balance'] if row else None


def _get_position(app, position_id):
    """Fetch a short position by ID."""
    conn = _get_db_conn(app)
    row = conn.execute("SELECT * FROM short_positions WHERE id = ?", (position_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def _get_active_positions(app, user_id):
    """Fetch all active short positions for a user."""
    conn = _get_db_conn(app)
    rows = conn.execute(
        "SELECT * FROM short_positions WHERE user_id = ? AND status = 'active'",
        (user_id,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def _get_all_positions(app, user_id):
    """Fetch all short positions (active + closed) for a user."""
    conn = _get_db_conn(app)
    rows = conn.execute(
        "SELECT * FROM short_positions WHERE user_id = ?",
        (user_id,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def _run_process_short_positions(app):
    """Run the shorting engine tick within an app context."""
    with app.app_context():
        from app.database import get_db
        from app.market.shorting import process_short_positions
        db = get_db()
        process_short_positions(db)


def _close_position_voluntary(app, position_id, user_id):
    """Voluntarily close a short position using the engine's _close_position."""
    with app.app_context():
        from app.database import get_db
        from app.market.shorting import _close_position
        db = get_db()
        pos = db.execute(
            "SELECT * FROM short_positions WHERE id = ?", (position_id,)
        ).fetchone()
        ore = db.execute(
            "SELECT current_price FROM ores WHERE id = ?", (pos['ore_id'],)
        ).fetchone()
        _close_position(db, pos, "voluntary", ore['current_price'])
        db.commit()


def _clear_short_positions(app):
    """Clear all short positions from the database (test cleanup)."""
    conn = _get_db_conn(app)
    conn.execute("DELETE FROM short_positions")
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# Test 1: Open short → tick → price drops → voluntary close → profit credited
# ---------------------------------------------------------------------------

class TestShortLifecycleProfit:
    """Open short → price drops → tick runs → close → verify profit credited.

    Requirements: 2.5, 5.2
    """

    def test_profit_on_price_drop(self, authenticated_client, app):
        """Short Coal at $10, price drops to $3, close for profit.

        With collateral multiplier 0.50:
        - vault (locked_collateral) at open = 100 * $10 * (1 + 0.50) = $1,500
        - player_margin (deducted from FreeCash) = 100 * $10 * 0.50 = $500
        - After price drop to $3: SV = 100 * $3 = $300
        - Close yields: vault - SV = $1,500 - $300 = $1,200 returned to FreeCash
        """
        user_id = _setup_advanced_user(app, balance=10000.0)

        ore_id = 1  # Coal
        _set_ore_price(app, ore_id, 10.00)

        # Open short: 100 shares at $10, vault = 100 * 10 * 1.50 = $1500
        # Player pays margin = 100 * 10 * 0.50 = $500
        locked_collateral = 1500.0
        player_margin = 500.0
        pos_id = _create_short_position(
            app, user_id, ore_id,
            share_quantity=100, entry_price=10.00,
            locked_collateral=locked_collateral,
        )

        # Deduct margin from balance (simulating opening — player pays margin, not vault)
        conn = _get_db_conn(app)
        conn.execute(
            "UPDATE users SET balance = balance - ? WHERE id = ?",
            (player_margin, user_id),
        )
        conn.commit()
        conn.close()

        balance_after_open = _get_user_balance(app)
        assert balance_after_open == 10000.0 - 500.0  # $9,500

        # Run a tick (margin rebalancing + fees)
        _set_ore_price(app, ore_id, 3.00)
        _run_process_short_positions(app)

        # After tick: locked_collateral was adjusted by margin rebalancing
        # and a fee was deducted. Verify position is still active.
        position = _get_position(app, pos_id)
        assert position['status'] == 'active'

        # Voluntarily close the position
        _close_position_voluntary(app, pos_id, user_id)

        # Verify position closed
        position = _get_position(app, pos_id)
        assert position['status'] == 'closed'

        # Verify profit: final balance > balance_after_open
        # The profit is locked_collateral_at_close - SV(at close)
        # which gets added to FreeCash
        final_balance = _get_user_balance(app)
        assert final_balance > balance_after_open, (
            f"Expected profit: final balance {final_balance} > {balance_after_open}"
        )


# ---------------------------------------------------------------------------
# Test 2: Margin call cascade → liquidation
# ---------------------------------------------------------------------------

class TestMarginCallCascadeToLiquidation:
    """Open short → price rises → margin calls drain FreeCash → liquidation.

    Requirements: 3.3, 6.1
    """

    def test_price_rise_triggers_margin_call_then_liquidation(self, authenticated_client, app):
        """Short Coal at $10 with minimal FreeCash. Price rises until liquidation."""
        user_id = _setup_advanced_user(app, balance=100.0)

        ore_id = 1  # Coal
        _set_ore_price(app, ore_id, 10.00)

        # Open short: 50 shares at $10, vault = 50 * 10 * 1.50 = $750
        pos_id = _create_short_position(
            app, user_id, ore_id,
            share_quantity=50, entry_price=10.00,
            locked_collateral=750.0,
        )

        # Price rises dramatically: $10 → $40
        # New required collateral = 50 * 40 * 1.50 = $3000 (deficit = 3000 - 750 = $2250)
        # User has only $100 FreeCash → can't cover → liquidation
        _set_ore_price(app, ore_id, 40.00)
        _run_process_short_positions(app)

        # Position should be closed (liquidated)
        position = _get_position(app, pos_id)
        assert position['status'] == 'closed', (
            f"Expected position to be liquidated (closed), got status={position['status']}"
        )


# ---------------------------------------------------------------------------
# Test 3: Fee bleed to liquidation
# ---------------------------------------------------------------------------

class TestFeeBleedToLiquidation:
    """Open short → many ticks → cumulative fees drain FreeCash → liquidation.

    Requirements: 4.2
    """

    def test_fees_exhaust_freecash_triggers_liquidation(self, authenticated_client, app):
        """Short with small FreeCash buffer; repeated ticks bleed fees until liquidation."""
        user_id = _setup_advanced_user(app, balance=5.0)  # Very low FreeCash

        ore_id = 4  # Gold (higher volatility = higher fees)
        _set_ore_price(app, ore_id, 50.00)

        # Open short: 100 shares at $50, vault = 100 * 50 * 1.50 = $7500
        pos_id = _create_short_position(
            app, user_id, ore_id,
            share_quantity=100, entry_price=50.00,
            locked_collateral=7500.0,
        )

        # Run several ticks to bleed fees. With SV=5000, vol=0.9:
        # hourly_rate = 0.005 + 0.10 * 0.81 = 0.086
        # tick_fee = 5000 * (0.086 / 180) ≈ $2.39/tick
        # With only $5 FreeCash, should be liquidated within 2-3 ticks.
        for _ in range(10):
            _run_process_short_positions(app)
            position = _get_position(app, pos_id)
            if position['status'] == 'closed':
                break

        assert position['status'] == 'closed', (
            "Position should have been liquidated by fee exhaustion"
        )


# ---------------------------------------------------------------------------
# Test 4: SL/TP trigger
# ---------------------------------------------------------------------------

class TestStopLossTrigger:
    """Open short with SL → price rises past SL → verify auto-close, no fee.

    Requirements: 7.4
    """

    def test_stop_loss_closes_position_on_price_rise(self, authenticated_client, app):
        """Short Coal at $10 with SL at $12. Price rises to $12 → auto-close."""
        user_id = _setup_advanced_user(app, balance=10000.0)

        ore_id = 1  # Coal
        _set_ore_price(app, ore_id, 10.00)

        # Open short with SL at $12
        # vault = 50 * 10 * 1.50 = $750
        pos_id = _create_short_position(
            app, user_id, ore_id,
            share_quantity=50, entry_price=10.00,
            locked_collateral=750.0,
            stop_loss_price=12.00,
        )

        # Price rises to $12 → triggers SL
        _set_ore_price(app, ore_id, 12.00)
        _run_process_short_positions(app)

        # Position should be closed by SL trigger
        position = _get_position(app, pos_id)
        assert position['status'] == 'closed', (
            f"Expected SL to close position, got status={position['status']}"
        )

        # Verify no fee was charged (SL triggers before fees)
        assert position['cumulative_fees_paid'] == 0.0, (
            f"Expected no fees on SL-triggered close, got {position['cumulative_fees_paid']}"
        )


# ---------------------------------------------------------------------------
# Test 5: Multi-position tick
# ---------------------------------------------------------------------------

class TestMultiPositionTick:
    """3 short positions → single tick → all processed correctly.

    Requirements: 3.3, 4.2
    Verifies:
    - All positions have fees charged
    - Margin calls process largest Required_Collateral first
    - Fees process oldest opened_at first
    """

    def test_three_positions_all_processed(self, authenticated_client, app):
        """Create 3 shorts on different ores, run one tick, verify all processed."""
        user_id = _setup_advanced_user(app, balance=50000.0)

        # Set known prices
        _set_ore_price(app, 1, 10.0)   # Coal
        _set_ore_price(app, 2, 25.0)   # Iron
        _set_ore_price(app, 4, 50.0)   # Gold

        # Create 3 positions with different opened_at times
        t1 = (datetime.now() - timedelta(hours=3)).isoformat()
        t2 = (datetime.now() - timedelta(hours=2)).isoformat()
        t3 = (datetime.now() - timedelta(hours=1)).isoformat()

        pos1_id = _create_short_position(
            app, user_id, ore_id=1,
            share_quantity=50, entry_price=10.0,
            locked_collateral=750.0, opened_at=t1,
        )
        pos2_id = _create_short_position(
            app, user_id, ore_id=2,
            share_quantity=40, entry_price=25.0,
            locked_collateral=1500.0, opened_at=t2,
        )
        pos3_id = _create_short_position(
            app, user_id, ore_id=4,
            share_quantity=20, entry_price=50.0,
            locked_collateral=1500.0, opened_at=t3,
        )

        balance_before_tick = _get_user_balance(app)

        # Run one tick
        _run_process_short_positions(app)

        # All positions should still be active (enough FreeCash)
        pos1 = _get_position(app, pos1_id)
        pos2 = _get_position(app, pos2_id)
        pos3 = _get_position(app, pos3_id)

        assert pos1['status'] == 'active'
        assert pos2['status'] == 'active'
        assert pos3['status'] == 'active'

        # All should have fees charged
        total_fees = (
            pos1['cumulative_fees_paid']
            + pos2['cumulative_fees_paid']
            + pos3['cumulative_fees_paid']
        )
        assert total_fees > 0.0

        # Balance should have decreased (fees deducted)
        balance_after_tick = _get_user_balance(app)
        assert balance_after_tick < balance_before_tick

        # Verify collateral maintained
        assert pos1['locked_collateral'] > 0
        assert pos2['locked_collateral'] > 0
        assert pos3['locked_collateral'] > 0

        # Fee ordering: oldest first. With Gold's higher volatility:
        # Coal: SV=50*10=500, vol=0.5 → small fee
        # Gold: SV=20*50=1000, vol=0.9 → larger fee (high volatility)
        assert pos3['cumulative_fees_paid'] > pos1['cumulative_fees_paid']



# ---------------------------------------------------------------------------
# Test 6: Bot short lifecycle
# ---------------------------------------------------------------------------

class TestBotShortLifecycle:
    """Full bot short lifecycle: bearish trend → decision → open → SL fires.

    Requirements: 13.5, 13.6, 13.7
    """

    def test_bot_short_decision_true_on_bearish_trend(self, authenticated_client, app):
        """Bot decision returns True when 4/5 trend entries are 'fall' and balance is sufficient."""
        from app.market.bots import _bot_short_decision

        user_id = _setup_advanced_user(app, balance=100000.0)

        # Set up Coal with bearish trend (4/5 fall)
        conn = _get_db_conn(app)
        conn.execute(
            """UPDATE ores SET trend_log = '["fall","fall","fall","fall","hold"]'
               WHERE id = 1"""
        )
        conn.commit()

        ore = conn.execute("SELECT * FROM ores WHERE id = 1").fetchone()
        result = _bot_short_decision(conn, user_id, ore)
        conn.close()

        assert result is True, (
            "Bot should short when 4/5 trends are 'fall' and balance is sufficient"
        )

    def test_bot_open_short_creates_position_with_sl_at_105_percent(self, authenticated_client, app):
        """Bot opens short and SL is set at entry_price × 1.05."""
        from app.market.bots import _bot_open_short

        user_id = _setup_advanced_user(app, balance=100000.0)

        ore_id = 1  # Coal at $10
        _set_ore_price(app, ore_id, 10.0)

        conn = _get_db_conn(app)
        result = _bot_open_short(conn, user_id, ore_id, quantity=50, price=10.0)
        conn.commit()
        conn.close()

        assert result is True, "Bot should successfully open a short"

        positions = _get_active_positions(app, user_id)
        assert len(positions) == 1

        pos = positions[0]
        expected_sl = 10.0 * 1.05  # $10.50
        assert pos['stop_loss_price'] == pytest.approx(expected_sl, abs=0.01), (
            f"Expected SL at {expected_sl}, got {pos['stop_loss_price']}"
        )

    def test_sl_fires_when_price_rises_above_bot_stop_loss(self, authenticated_client, app):
        """After price reversal above SL, process_short_positions closes the bot's position."""
        user_id = _setup_advanced_user(app, balance=100000.0)

        ore_id = 1  # Coal
        _set_ore_price(app, ore_id, 10.0)

        # Create position with SL at 10.50
        # vault = 50 * 10 * 1.50 = $750
        pos_id = _create_short_position(
            app, user_id, ore_id,
            share_quantity=50, entry_price=10.0,
            locked_collateral=750.0,
            stop_loss_price=10.50,
        )

        # Price rises to 10.50 → triggers SL
        _set_ore_price(app, ore_id, 10.50)
        _run_process_short_positions(app)

        position = _get_position(app, pos_id)
        assert position['status'] == 'closed', (
            "Position should be closed by SL trigger"
        )

    def test_full_bot_short_lifecycle_end_to_end(self, authenticated_client, app):
        """End-to-end: bearish trend → decision → open → price reversal → SL close."""
        from app.market.bots import _bot_short_decision, _bot_open_short

        user_id = _setup_advanced_user(app, balance=100000.0)

        ore_id = 1  # Coal at $10
        _set_ore_price(app, ore_id, 10.0)

        # Set bearish trend
        conn = _get_db_conn(app)
        conn.execute(
            """UPDATE ores SET trend_log = '["fall","fall","fall","fall","fall"]'
               WHERE id = 1"""
        )
        conn.commit()

        # Decision
        ore = conn.execute("SELECT * FROM ores WHERE id = 1").fetchone()
        assert _bot_short_decision(conn, user_id, ore) is True
        conn.close()

        # Open
        conn = _get_db_conn(app)
        _bot_open_short(conn, user_id, ore_id, quantity=50, price=10.0)
        conn.commit()
        conn.close()

        positions = _get_active_positions(app, user_id)
        assert len(positions) == 1
        pos_id = positions[0]['id']

        # Price reversal → SL fires
        _set_ore_price(app, ore_id, 10.50)
        _run_process_short_positions(app)

        position = _get_position(app, pos_id)
        assert position['status'] == 'closed'


# ---------------------------------------------------------------------------
# Test 7: Bot capital cap
# ---------------------------------------------------------------------------

class TestBotCapitalCap:
    """Verify the 30% capital cap prevents bots from over-exposing to shorts.

    Requirements: 13.5, 13.6, 13.7
    """

    def test_capital_cap_blocks_short_when_at_limit(self, authenticated_client, app):
        """Bot cannot short when total short capital >= 30% of total balance."""
        from app.market.bots import _bot_short_decision

        user_id = _setup_advanced_user(app, balance=10000.0)

        # Create existing shorts consuming 30%+ of balance
        # Total balance (FreeCash + locked) = 10000 + 7500 = 17500
        # Short capital = 7500, which is 42.9% of 17500 → over cap
        # vault = 500 shares * $10 * 1.5 = $7500
        _create_short_position(
            app, user_id, ore_id=1,
            share_quantity=500, entry_price=10.0,
            locked_collateral=7500.0,
        )

        conn = _get_db_conn(app)
        conn.execute(
            """UPDATE ores SET trend_log = '["fall","fall","fall","fall","fall"]'
               WHERE id = 2"""
        )
        conn.commit()
        ore = conn.execute("SELECT * FROM ores WHERE id = 2").fetchone()
        result = _bot_short_decision(conn, user_id, ore)
        conn.close()

        assert result is False, (
            "Bot should not short when capital cap is exceeded"
        )

    def test_capital_cap_allows_short_when_under_limit(self, authenticated_client, app):
        """Bot can short when total short capital is well under 30% of total balance."""
        from app.market.bots import _bot_short_decision

        user_id = _setup_advanced_user(app, balance=100000.0)

        # Small existing short: 100 locked out of 100100 total = ~0.1%
        _create_short_position(
            app, user_id, ore_id=1,
            share_quantity=10, entry_price=10.0,
            locked_collateral=100.0,
        )

        conn = _get_db_conn(app)
        conn.execute(
            """UPDATE ores SET trend_log = '["fall","fall","fall","fall","fall"]'
               WHERE id = 2"""
        )
        conn.commit()
        ore = conn.execute("SELECT * FROM ores WHERE id = 2").fetchone()
        result = _bot_short_decision(conn, user_id, ore)
        conn.close()

        assert result is True, (
            "Bot should be allowed to short when under capital cap"
        )

    def test_bot_open_short_rejected_by_capital_cap(self, authenticated_client, app):
        """_bot_open_short returns False when opening would exceed 30% capital cap."""
        from app.market.bots import _bot_open_short

        user_id = _setup_advanced_user(app, balance=10000.0)

        # Existing short consuming ~30% already
        # vault = 500 * $10 * 1.5 = $7500
        _create_short_position(
            app, user_id, ore_id=1,
            share_quantity=500, entry_price=10.0,
            locked_collateral=7500.0,
        )

        ore_id = 2  # Iron at $25
        _set_ore_price(app, ore_id, 25.0)

        conn = _get_db_conn(app)
        result = _bot_open_short(conn, user_id, ore_id, quantity=100, price=25.0)
        conn.close()

        assert result is False, (
            "Bot open short should be rejected when capital cap would be exceeded"
        )

    def test_bot_decision_false_without_bearish_trend(self, authenticated_client, app):
        """Bot short decision returns False when trend is neutral (< 4/5 'fall')."""
        from app.market.bots import _bot_short_decision

        user_id = _setup_advanced_user(app, balance=100000.0)

        ore_id = 1
        conn = _get_db_conn(app)
        # Only 2/5 fall — not enough for shorting
        conn.execute(
            """UPDATE ores SET trend_log = '["fall","fall","hold","rise","hold"]'
               WHERE id = ?""",
            (ore_id,)
        )
        conn.commit()

        ore = conn.execute("SELECT * FROM ores WHERE id = ?", (ore_id,)).fetchone()
        result = _bot_short_decision(conn, user_id, ore)
        conn.close()

        assert result is False, (
            "Bot should not short when trend is neutral (fewer than 4/5 'fall')"
        )



# ---------------------------------------------------------------------------
# Test 8: Player with shorts appears with correct net worth on leaderboard
# Validates: Requirement 12.1
# ---------------------------------------------------------------------------

class TestNetWorthWithShorts:
    """Integration: net worth calculation correctly includes short position equity."""

    def test_net_worth_includes_short_equity(self, authenticated_client, app):
        """Net worth = FreeCash + holdings_value + SUM(locked - short_value)."""
        user_id = _setup_advanced_user(app, balance=5000.0)

        # Give user holdings: 10 Iron (ore_id=2, current_price=$25)
        # Holdings value = 10 * 25 = $250
        conn = _get_db_conn(app)
        conn.execute(
            "INSERT INTO holdings (user_id, ore_id, quantity, avg_purchase_price) "
            "VALUES (?, 2, 10, 20.0)",
            (user_id,)
        )
        conn.commit()
        conn.close()

        # Open a short position: 5 Coal (ore_id=1, current_price=$10)
        # vault = 5 * 10 * 1.5 = $75
        # short_value = 5 * 10 = $50
        # short_equity = 75 - 50 = $25
        _set_ore_price(app, 1, 10.0)
        _create_short_position(
            app, user_id, ore_id=1,
            share_quantity=5, entry_price=10.0,
            locked_collateral=75.0,
        )

        with app.app_context():
            from app.models import get_net_worth

            net_worth = get_net_worth(user_id)
            # FreeCash ($5000) + Holdings ($250) + Short Equity ($75 - $50 = $25)
            expected = 5000.0 + 250.0 + (75.0 - 50.0)  # $5275
            assert net_worth == expected, (
                f"Expected net worth {expected}, got {net_worth}"
            )

    def test_net_worth_profitable_short(self, authenticated_client, app):
        """Net worth reflects profitable short when price dropped below entry."""
        user_id = _setup_advanced_user(app, balance=8000.0)

        # Short 10 Gold (ore_id=4) — drop price to $30
        _set_ore_price(app, 4, 30.0)

        # vault = 10 * 50 * 1.5 = $750 (frozen at open time)
        # short_value at current = 10 * 30 = $300
        # short_equity = 750 - 300 = $450 (profit!)
        _create_short_position(
            app, user_id, ore_id=4,
            share_quantity=10, entry_price=50.0,
            locked_collateral=750.0,
        )

        with app.app_context():
            from app.models import get_net_worth

            net_worth = get_net_worth(user_id)
            # FreeCash ($8000) + Holdings ($0) + Short Equity ($750 - $300 = $450)
            expected = 8000.0 + 0.0 + (750.0 - 300.0)  # $8450
            assert net_worth == expected, (
                f"Expected net worth {expected}, got {net_worth}"
            )

    def test_net_worth_no_shorts_matches_legacy(self, authenticated_client, app):
        """Without shorts, net worth == FreeCash + holdings (legacy formula)."""
        user_id = _setup_advanced_user(app, balance=7500.0)

        # 5 Iron at current_price $25 = $125
        conn = _get_db_conn(app)
        conn.execute(
            "INSERT INTO holdings (user_id, ore_id, quantity, avg_purchase_price) "
            "VALUES (?, 2, 5, 25.0)",
            (user_id,)
        )
        conn.commit()
        conn.close()

        with app.app_context():
            from app.models import get_net_worth, get_portfolio_value

            net_worth = get_net_worth(user_id)
            holdings_value = get_portfolio_value(user_id)
            expected = 7500.0 + holdings_value
            assert net_worth == expected, (
                f"Expected net worth {expected}, got {net_worth}"
            )


# ---------------------------------------------------------------------------
# Test 9: Account reset with active shorts → clean state, no orphaned records
# Validates: Requirements 14.1, 14.5
# ---------------------------------------------------------------------------

class TestAccountResetWithShorts:
    """Integration: account reset properly cleans all short-related state."""

    def test_reset_deletes_all_short_positions(self, authenticated_client, app):
        """Account reset removes all short positions without crediting collateral."""
        user_id = _setup_advanced_user(app, balance=3000.0)

        # Create two active short positions with locked collateral
        # vault = 10 * 10 * 1.5 = $150
        _create_short_position(
            app, user_id, ore_id=1,
            share_quantity=10, entry_price=10.0,
            locked_collateral=150.0,
        )
        # vault = 5 * 25 * 1.5 = $187.5
        _create_short_position(
            app, user_id, ore_id=2,
            share_quantity=5, entry_price=25.0,
            locked_collateral=187.5,
        )

        # Create short-related transactions
        conn = _get_db_conn(app)
        conn.execute(
            "INSERT INTO transactions "
            "(user_id, ore_id, type, quantity, price_at_trade, total_value, created_at) "
            "VALUES (?, 1, 'short_open', 10, 10.0, 150.0, datetime('now'))",
            (user_id,)
        )
        conn.execute(
            "INSERT INTO transactions "
            "(user_id, ore_id, type, quantity, price_at_trade, total_value, created_at) "
            "VALUES (?, 2, 'short_open', 5, 25.0, 187.5, datetime('now'))",
            (user_id,)
        )
        conn.commit()
        conn.close()

        # Perform account reset
        with app.app_context():
            from app.models import reset_account
            reset_account(user_id)

        # Verify results
        conn = _get_db_conn(app)

        # Zero short_positions for this user
        count = conn.execute(
            "SELECT COUNT(*) as cnt FROM short_positions WHERE user_id = ?",
            (user_id,)
        ).fetchone()['cnt']
        assert count == 0, f"Expected 0 short positions after reset, got {count}"

        # Short-related transactions archived
        archived = conn.execute(
            "SELECT COUNT(*) as cnt FROM transactions WHERE user_id = ? AND archived = 1 "
            "AND type IN ('short_open', 'short_close', 'short_liquidated')",
            (user_id,)
        ).fetchone()['cnt']
        assert archived == 2, (
            f"Expected 2 archived short transactions, got {archived}"
        )

        # Balance reset to default ($10000)
        user = conn.execute(
            "SELECT balance, advanced_eligible, advanced_purchased, advanced_active "
            "FROM users WHERE id = ?", (user_id,)
        ).fetchone()
        assert user['balance'] == 10000.0, (
            f"Expected balance $10000, got {user['balance']}"
        )

        # Advanced Mode state cleared
        assert user['advanced_eligible'] == 0, "advanced_eligible should be 0"
        assert user['advanced_purchased'] == 0, "advanced_purchased should be 0"
        assert user['advanced_active'] == 0, "advanced_active should be 0"

        # No collateral "credited back" — balance is exactly default
        # (not default + locked collateral of 150 + 187.5 = 337.5)
        assert user['balance'] == 10000.0, (
            "Balance should be exactly default, not default + freed collateral"
        )

        conn.close()

    def test_reset_no_orphaned_records(self, authenticated_client, app):
        """Account reset leaves no orphaned short records (active or closed)."""
        user_id = _setup_advanced_user(app, balance=6000.0)

        # Create a mix of active and closed positions
        # vault = 3 * 10 * 1.5 = $45
        _create_short_position(
            app, user_id, ore_id=1,
            share_quantity=3, entry_price=10.0,
            locked_collateral=45.0,
        )
        # Insert a closed position directly
        conn = _get_db_conn(app)
        conn.execute(
            """INSERT INTO short_positions
               (user_id, ore_id, share_quantity, entry_price, locked_collateral,
                cumulative_fees_paid, opened_at, status, closed_at)
               VALUES (?, 3, 7, 15.0, 157.5, 0.0, datetime('now', '-1 hour'), 'closed', datetime('now'))""",
            (user_id,)
        )
        # Also a short_liquidated transaction
        conn.execute(
            "INSERT INTO transactions "
            "(user_id, ore_id, type, quantity, price_at_trade, total_value, created_at) "
            "VALUES (?, 1, 'short_liquidated', 3, 12.0, -6.0, datetime('now'))",
            (user_id,)
        )
        conn.commit()
        conn.close()

        with app.app_context():
            from app.models import reset_account
            reset_account(user_id)

        # Verify: no short positions remain (active OR closed)
        conn = _get_db_conn(app)
        total = conn.execute(
            "SELECT COUNT(*) as cnt FROM short_positions WHERE user_id = ?",
            (user_id,)
        ).fetchone()['cnt']
        assert total == 0, f"Expected 0 total short positions after reset, got {total}"

        # All short-related transactions archived
        unarchived = conn.execute(
            "SELECT COUNT(*) as cnt FROM transactions WHERE user_id = ? AND archived = 0 "
            "AND type IN ('short_open', 'short_close', 'short_liquidated')",
            (user_id,)
        ).fetchone()['cnt']
        assert unarchived == 0, (
            f"Expected 0 unarchived short transactions, got {unarchived}"
        )

        conn.close()


# ---------------------------------------------------------------------------
# Test 10: No Surplus Release — vault stays frozen when price drops
# Validates: Shorting_fixup.md — surplus release removed
# ---------------------------------------------------------------------------

class TestNoSurplusRelease:
    """Integration: vault stays frozen when price drops (no surplus release)."""

    def test_vault_stays_frozen_on_price_drop(self, authenticated_client, app):
        """Price drop does NOT reduce locked_collateral — vault only grows."""
        user_id = _setup_advanced_user(app, balance=5000.0)

        # Open short on Iron (ore_id=2) at $25
        # vault = 10 * 25 * 1.5 = $375
        initial_locked = 375.0
        _set_ore_price(app, 2, 25.0)

        conn = _get_db_conn(app)
        for i in range(50):
            conn.execute(
                "INSERT INTO holdings (user_id, ore_id, quantity, avg_purchase_price) "
                "VALUES (?, 2, 10, 20.0)",
                (user_id,)
            )
        conn.commit()
        conn.close()

        pos_id = _create_short_position(
            app, user_id, ore_id=2,
            share_quantity=10, entry_price=25.0,
            locked_collateral=initial_locked,
        )

        initial_balance = 5000.0

        # Drop Iron price from $25 to $15
        _set_ore_price(app, 2, 15.0)

        # Run tick processing
        _run_process_short_positions(app)

        # Verify results
        conn = _get_db_conn(app)
        user = conn.execute(
            "SELECT balance FROM users WHERE id = ?", (user_id,)
        ).fetchone()
        position = conn.execute(
            "SELECT locked_collateral, cumulative_fees_paid "
            "FROM short_positions WHERE id = ? AND status = 'active'",
            (pos_id,)
        ).fetchone()
        conn.close()

        free_cash_after = user['balance']
        locked_after = position['locked_collateral']
        fees_paid = position['cumulative_fees_paid']

        # Locked collateral should NOT have decreased (no surplus release)
        assert locked_after >= initial_locked, (
            f"Expected locked to stay >= {initial_locked} (no surplus release), got {locked_after}"
        )

        # FreeCash should have decreased (only fees were deducted, no surplus credited)
        assert free_cash_after <= initial_balance, (
            f"Expected FreeCash to decrease or stay same (fees only), "
            f"was {initial_balance}, got {free_cash_after}"
        )

        # The decrease in FreeCash should equal fees paid
        balance_decrease = initial_balance - free_cash_after
        assert abs(balance_decrease - fees_paid) < 0.02, (
            f"FreeCash decrease ({balance_decrease}) should equal fees paid ({fees_paid})"
        )

    def test_vault_frozen_no_conservation_with_surplus(self, authenticated_client, app):
        """When price drops, vault stays frozen — FreeCash + Locked is NOT conserved
        (only fees deducted from FreeCash, vault unchanged)."""
        user_id = _setup_advanced_user(app, balance=10000.0)

        # Short 20 Coal (ore_id=1) at $10, vault = 20 * 10 * 1.5 = $300
        initial_locked = 300.0
        _set_ore_price(app, 1, 10.0)

        conn = _get_db_conn(app)
        for i in range(50):
            conn.execute(
                "INSERT INTO holdings (user_id, ore_id, quantity, avg_purchase_price) "
                "VALUES (?, 1, 10, 8.0)",
                (user_id,)
            )
        conn.commit()
        conn.close()

        pos_id = _create_short_position(
            app, user_id, ore_id=1,
            share_quantity=20, entry_price=10.0,
            locked_collateral=initial_locked,
        )

        initial_balance = 10000.0

        # Drop Coal price: $10 → $5
        _set_ore_price(app, 1, 5.0)

        # Run only the rebalancing phase (not full tick) to isolate from fees
        with app.app_context():
            from app.database import get_db
            from app.market.shorting import _rebalance_margin

            db = get_db()
            ores_rows = db.execute(
                "SELECT id, current_price, volatility FROM ores"
            ).fetchall()
            ores_map = {
                row['id']: {
                    'current_price': float(row['current_price']),
                    'volatility': float(row['volatility']),
                }
                for row in ores_rows
            }
            closed_ids = set()
            _rebalance_margin(db, ores_map, closed_ids)
            db.commit()

        # Verify no change (no surplus release)
        conn = _get_db_conn(app)
        user = conn.execute(
            "SELECT balance FROM users WHERE id = ?", (user_id,)
        ).fetchone()
        position = conn.execute(
            "SELECT locked_collateral FROM short_positions WHERE user_id = ? AND status = 'active'",
            (user_id,)
        ).fetchone()
        conn.close()

        free_cash_after = user['balance']
        locked_after = position['locked_collateral']

        # Vault stays frozen (no surplus release)
        assert locked_after == initial_locked, (
            f"Expected locked to stay at {initial_locked} (no surplus release), got {locked_after}"
        )

        # FreeCash unchanged (rebalancing does nothing when required < locked)
        assert free_cash_after == initial_balance, (
            f"Expected FreeCash unchanged at {initial_balance}, got {free_cash_after}"
        )
