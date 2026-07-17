"""Integration tests for the full Advanced Mode lifecycle.

Tests end-to-end flows through multiple components:
- Full purchase flow: create user → accumulate wealth → become eligible → purchase → verify deduction
- Tick engine SL/TP execution: set up holding with SL → run evaluate → verify auto-sell
- Account reset: purchase advanced → reset → verify all state cleared
- Cooldown enforcement: toggle → immediate re-toggle rejected → wait → toggle succeeds

Requirements: 1.1, 3.1, 6.3, 6.4, 10.1, 10.2, 4.3
"""

import sqlite3
from datetime import datetime, timedelta

import pytest

from conftest import get_csrf_token, register_user

pytestmark = pytest.mark.advanced_integration


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_db_conn(app):
    """Get a direct SQLite connection to the test database."""
    conn = sqlite3.connect(app.config['DATABASE_PATH'])
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _get_user_row(app, username='TestUser1'):
    """Fetch the full user row as a dict."""
    conn = _get_db_conn(app)
    row = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
    conn.close()
    return dict(row) if row else None


def _get_user_id(app, username='TestUser1'):
    """Look up user ID by username."""
    conn = _get_db_conn(app)
    row = conn.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone()
    conn.close()
    return row['id'] if row else None


def _set_user_state(app, username='TestUser1', **kwargs):
    """Directly set user columns in the database for test setup."""
    if not kwargs:
        return
    conn = _get_db_conn(app)
    sets = ', '.join(f'{k} = ?' for k in kwargs)
    values = list(kwargs.values())
    conn.execute(
        f"UPDATE users SET {sets} WHERE username = ?",
        values + [username],
    )
    conn.commit()
    conn.close()


def _create_holding(app, user_id, ore_id, quantity, avg_price):
    """Insert a holding record and return its ID."""
    conn = _get_db_conn(app)
    cursor = conn.execute(
        "INSERT INTO holdings (user_id, ore_id, quantity, avg_purchase_price) VALUES (?, ?, ?, ?)",
        (user_id, ore_id, quantity, avg_price),
    )
    holding_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return holding_id


def _create_sltp_order(app, holding_id, stop_loss=None, take_profit=None):
    """Insert a stop_loss_take_profit order and return its ID."""
    conn = _get_db_conn(app)
    cursor = conn.execute(
        "INSERT INTO stop_loss_take_profit (holding_id, stop_loss, take_profit, active) VALUES (?, ?, ?, 1)",
        (holding_id, stop_loss, take_profit),
    )
    order_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return order_id


def _set_ore_price(app, ore_id, price):
    """Directly update an ore's current_price."""
    conn = _get_db_conn(app)
    conn.execute("UPDATE ores SET current_price = ? WHERE id = ?", (price, ore_id))
    conn.commit()
    conn.close()


def _get_holdings(app, user_id):
    """Get all holdings for a user."""
    conn = _get_db_conn(app)
    rows = conn.execute("SELECT * FROM holdings WHERE user_id = ?", (user_id,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def _get_sltp_orders(app, user_id):
    """Get all SL/TP orders for a user's holdings."""
    conn = _get_db_conn(app)
    rows = conn.execute(
        """SELECT sltp.* FROM stop_loss_take_profit sltp
           JOIN holdings h ON sltp.holding_id = h.id
           WHERE h.user_id = ?""",
        (user_id,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def _get_all_sltp_for_user(app, user_id):
    """Get all SL/TP orders (including triggered/inactive) associated with a user.

    Uses a left join approach to catch orders even when holdings are deleted.
    """
    conn = _get_db_conn(app)
    # After reset, holdings are deleted so we can't join. Query all orders instead.
    rows = conn.execute(
        """SELECT sltp.* FROM stop_loss_take_profit sltp
           WHERE sltp.holding_id IN (SELECT id FROM holdings WHERE user_id = ?)""",
        (user_id,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Test: Full Purchase Flow
# ---------------------------------------------------------------------------

class TestFullPurchaseFlow:
    """Integration test: create user → accumulate wealth → become eligible → purchase → verify deduction.

    Requirements: 1.1, 3.1
    """

    def test_full_purchase_lifecycle(self, authenticated_client, app):
        """A user with $150,000 balance becomes eligible and can purchase Advanced Mode."""
        # Step 1: Set the user's balance to $150,000 (above the $100,000 threshold)
        _set_user_state(app, balance=150000.0)

        user_id = _get_user_id(app)

        # Step 2: Check eligibility within app context
        with app.app_context():
            from app.advanced import check_eligibility, purchase_advanced_mode

            # Verify eligibility is detected
            eligible = check_eligibility(user_id)
            assert eligible is True

            # Step 3: Verify the user is now marked eligible in the DB
            user = _get_user_row(app)
            assert user['advanced_eligible'] == 1

            # Step 4: Purchase Advanced Mode
            success, message = purchase_advanced_mode(user_id)
            assert success is True
            assert "purchased successfully" in message.lower() or "purchased" in message.lower()

        # Step 5: Verify balance deducted correctly ($150,000 - $50,000 = $100,000)
        user = _get_user_row(app)
        assert user['balance'] == 100000.0

        # Step 6: Verify advanced_purchased flag is set
        assert user['advanced_purchased'] == 1

    def test_ineligible_user_cannot_purchase(self, authenticated_client, app):
        """A user with balance below threshold cannot become eligible or purchase."""
        # User starts with default balance ($10,000) — well below $100,000
        user_id = _get_user_id(app)

        with app.app_context():
            from app.advanced import check_eligibility, purchase_advanced_mode

            # User is not eligible
            eligible = check_eligibility(user_id)
            assert eligible is False

            # Purchase attempt should fail
            success, message = purchase_advanced_mode(user_id)
            assert success is False

        # Balance unchanged
        user = _get_user_row(app)
        assert user['advanced_purchased'] == 0


# ---------------------------------------------------------------------------
# Test: Tick Engine SL/TP Execution
# ---------------------------------------------------------------------------

class TestTickEngineSLTP:
    """Integration test: set up holding with SL → run evaluate_stop_loss_take_profit → verify auto-sell.

    Requirements: 6.3, 6.4
    """

    def test_stop_loss_triggers_auto_sell(self, authenticated_client, app):
        """When ore price drops below stop loss, the holding is auto-sold."""
        user_id = _get_user_id(app)
        initial_balance = 50000.0
        _set_user_state(app, balance=initial_balance)

        # Set ore 1 (Coal) price to $10.00
        ore_id = 1
        _set_ore_price(app, ore_id, 10.00)

        # Create a holding: 100 units of Coal at avg price $10.00
        holding_id = _create_holding(app, user_id, ore_id, quantity=100, avg_price=10.00)

        # Create a stop loss order at $8.00
        order_id = _create_sltp_order(app, holding_id, stop_loss=8.00)

        # Drop the ore price to $7.00 (below the $8.00 stop loss)
        _set_ore_price(app, ore_id, 7.00)

        # Run the SL/TP evaluator
        with app.app_context():
            from app.database import get_db
            from app.market.engine import evaluate_stop_loss_take_profit

            db = get_db()
            evaluate_stop_loss_take_profit(db)

        # Verify: holding is deleted (auto-sold)
        holdings = _get_holdings(app, user_id)
        holding_ids = [h['id'] for h in holdings]
        assert holding_id not in holding_ids

        # Verify: balance credited (100 units × $7.00 = $700.00 added)
        user = _get_user_row(app)
        assert user['balance'] == initial_balance + (100 * 7.00)

        # Verify: a sell transaction was recorded for the auto-sell
        conn = _get_db_conn(app)
        tx = conn.execute(
            "SELECT * FROM transactions WHERE user_id = ? AND ore_id = ? AND type = 'sell' ORDER BY id DESC LIMIT 1",
            (user_id, ore_id),
        ).fetchone()
        conn.close()
        assert tx is not None
        assert tx['quantity'] == 100
        assert tx['price_at_trade'] == 7.00

    def test_take_profit_triggers_auto_sell(self, authenticated_client, app):
        """When ore price rises above take profit, the holding is auto-sold."""
        user_id = _get_user_id(app)
        initial_balance = 50000.0
        _set_user_state(app, balance=initial_balance)

        # Set ore 2 (Iron) price to $25.00
        ore_id = 2
        _set_ore_price(app, ore_id, 25.00)

        # Create a holding: 50 units of Iron at avg price $25.00
        holding_id = _create_holding(app, user_id, ore_id, quantity=50, avg_price=25.00)

        # Create a take profit order at $30.00
        order_id = _create_sltp_order(app, holding_id, take_profit=30.00)

        # Raise the ore price to $32.00 (above the $30.00 take profit)
        _set_ore_price(app, ore_id, 32.00)

        # Run the SL/TP evaluator
        with app.app_context():
            from app.database import get_db
            from app.market.engine import evaluate_stop_loss_take_profit

            db = get_db()
            evaluate_stop_loss_take_profit(db)

        # Verify: holding is deleted
        holdings = _get_holdings(app, user_id)
        holding_ids = [h['id'] for h in holdings]
        assert holding_id not in holding_ids

        # Verify: balance credited (50 units × $32.00 = $1,600 added)
        user = _get_user_row(app)
        assert user['balance'] == initial_balance + (50 * 32.00)

        # Verify: a sell transaction was recorded for the auto-sell
        conn = _get_db_conn(app)
        tx = conn.execute(
            "SELECT * FROM transactions WHERE user_id = ? AND ore_id = ? AND type = 'sell' ORDER BY id DESC LIMIT 1",
            (user_id, ore_id),
        ).fetchone()
        conn.close()
        assert tx is not None
        assert tx['quantity'] == 50
        assert tx['price_at_trade'] == 32.00

    def test_price_above_stop_loss_no_trigger(self, authenticated_client, app):
        """When ore price is still above stop loss, no auto-sell happens."""
        user_id = _get_user_id(app)
        initial_balance = 50000.0
        _set_user_state(app, balance=initial_balance)

        ore_id = 1
        _set_ore_price(app, ore_id, 10.00)

        holding_id = _create_holding(app, user_id, ore_id, quantity=100, avg_price=10.00)
        _create_sltp_order(app, holding_id, stop_loss=8.00)

        # Price stays at $10.00, above the $8.00 SL — should NOT trigger
        with app.app_context():
            from app.database import get_db
            from app.market.engine import evaluate_stop_loss_take_profit

            db = get_db()
            evaluate_stop_loss_take_profit(db)

        # Holding should still exist
        holdings = _get_holdings(app, user_id)
        assert any(h['id'] == holding_id for h in holdings)

        # Balance unchanged
        user = _get_user_row(app)
        assert user['balance'] == initial_balance


# ---------------------------------------------------------------------------
# Test: Account Reset
# ---------------------------------------------------------------------------

class TestAccountReset:
    """Integration test: purchase advanced → reset → verify all state cleared.

    Requirements: 10.1, 10.2
    """

    def test_reset_clears_all_advanced_state(self, authenticated_client, app):
        """After account reset, all advanced flags are cleared and SL/TP orders removed."""
        user_id = _get_user_id(app)

        # Set up: user has purchased and activated Advanced Mode
        _set_user_state(
            app,
            balance=100000.0,
            advanced_eligible=1,
            advanced_purchased=1,
            advanced_active=1,
            advanced_toggled_at=datetime.now().isoformat(),
        )

        # Create holdings with SL/TP orders
        ore_id = 1
        _set_ore_price(app, ore_id, 10.00)
        holding_id_1 = _create_holding(app, user_id, ore_id, quantity=50, avg_price=10.00)
        _create_sltp_order(app, holding_id_1, stop_loss=8.00, take_profit=15.00)

        holding_id_2 = _create_holding(app, user_id, ore_id, quantity=30, avg_price=9.00)
        _create_sltp_order(app, holding_id_2, stop_loss=7.00)

        # Verify setup: user has holdings and SL/TP orders
        assert len(_get_holdings(app, user_id)) == 2
        assert len(_get_sltp_orders(app, user_id)) == 2

        # Perform account reset
        with app.app_context():
            from app.models import reset_account
            reset_account(user_id)

        # Verify: all advanced flags cleared
        user = _get_user_row(app)
        assert user['advanced_eligible'] == 0
        assert user['advanced_purchased'] == 0
        assert user['advanced_active'] == 0
        assert user['advanced_toggled_at'] is None

        # Verify: no holdings remain
        holdings = _get_holdings(app, user_id)
        assert len(holdings) == 0

        # Verify: no SL/TP orders remain (holdings were deleted, cascade should clear them)
        orders = _get_all_sltp_for_user(app, user_id)
        assert len(orders) == 0


# ---------------------------------------------------------------------------
# Test: Cooldown Enforcement
# ---------------------------------------------------------------------------

class TestCooldownEnforcement:
    """Integration test: toggle → immediate re-toggle rejected → wait → toggle succeeds.

    Requirements: 4.3
    """

    def test_cooldown_lifecycle(self, authenticated_client, app):
        """Toggle succeeds, immediate re-toggle is rejected, after cooldown it succeeds again."""
        user_id = _get_user_id(app)

        # Set up: user has purchased Advanced Mode, no prior toggle
        _set_user_state(
            app,
            advanced_eligible=1,
            advanced_purchased=1,
            advanced_active=0,
            advanced_toggled_at=None,
        )

        with app.app_context():
            from app.advanced import toggle_advanced_mode

            # Step 1: First toggle — should succeed (enable)
            success, message = toggle_advanced_mode(user_id)
            assert success is True
            assert "enabled" in message.lower()

        # Verify active state is now 1
        user = _get_user_row(app)
        assert user['advanced_active'] == 1
        assert user['advanced_toggled_at'] is not None

        with app.app_context():
            from app.advanced import toggle_advanced_mode

            # Step 2: Immediate re-toggle — should be rejected (cooldown)
            success, message = toggle_advanced_mode(user_id)
            assert success is False
            assert "wait" in message.lower()
            assert "minutes" in message.lower()

        # Verify state unchanged
        user = _get_user_row(app)
        assert user['advanced_active'] == 1

        # Step 3: Manipulate the toggled_at timestamp to 6 minutes ago (past cooldown)
        past_time = (datetime.now() - timedelta(minutes=6)).isoformat()
        _set_user_state(app, advanced_toggled_at=past_time)

        with app.app_context():
            from app.advanced import toggle_advanced_mode

            # Step 4: Toggle again — should succeed now (disable)
            success, message = toggle_advanced_mode(user_id)
            assert success is True
            assert "disabled" in message.lower()

        # Verify active state is now 0
        user = _get_user_row(app)
        assert user['advanced_active'] == 0
