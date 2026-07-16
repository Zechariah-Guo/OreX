"""Trading test module for OreX.

Covers buy and sell operations, validation, atomicity, and edge cases.
"""

import sqlite3
from unittest.mock import patch

import pytest

from conftest import get_csrf_token, register_user

pytestmark = pytest.mark.trading


def _buy_ore(client, ore_id, quantity, follow_redirects=True):
    """Execute a full buy flow: initial POST then confirmed POST.

    Returns the final response (after confirmation).
    """
    # Step 1: Initial POST to get confirmation page
    get_resp = client.get(f'/market/{ore_id}')
    token = get_csrf_token(get_resp)
    confirm_resp = client.post(f'/trade/buy/{ore_id}', data={
        'quantity': quantity,
        'csrf_token': token,
    }, follow_redirects=True)

    # If we got redirected back (validation error), return that response
    if b'Confirm Buy' not in confirm_resp.data:
        return confirm_resp

    # Step 2: Confirmed POST to execute the trade
    token = get_csrf_token(confirm_resp)
    return client.post(f'/trade/buy/{ore_id}', data={
        'quantity': quantity,
        'confirmed': '1',
        'csrf_token': token,
    }, follow_redirects=follow_redirects)


def _sell_ore(client, ore_id, quantity, follow_redirects=True):
    """Execute a full sell flow: initial POST then confirmed POST.

    Returns the final response (after confirmation).
    """
    # Step 1: Initial POST to get confirmation page
    get_resp = client.get(f'/market/{ore_id}')
    token = get_csrf_token(get_resp)
    confirm_resp = client.post(f'/trade/sell/{ore_id}', data={
        'quantity': quantity,
        'csrf_token': token,
    }, follow_redirects=True)

    # If we got redirected back (validation error), return that response
    if b'Confirm Sell' not in confirm_resp.data:
        return confirm_resp

    # Step 2: Confirmed POST to execute the trade
    token = get_csrf_token(confirm_resp)
    return client.post(f'/trade/sell/{ore_id}', data={
        'quantity': quantity,
        'confirmed': '1',
        'csrf_token': token,
    }, follow_redirects=follow_redirects)


class TestTrading:
    """Tests for trading — maps to Testing_Log.md Trading section."""

    def test_valid_buy_decreases_balance_creates_holding_and_transaction(
        self, authenticated_client, app
    ):
        """TC: valid buy decreases balance, creates/updates holding, creates transaction.

        Validates: Requirements 4.1
        """
        ore_id = 1  # Coal, current_price = 10.00
        quantity = 5
        expected_cost = 5 * 10.00  # 50.00

        response = _buy_ore(authenticated_client, ore_id, str(quantity))
        assert response.status_code == 200

        # Verify balance decreased
        conn = sqlite3.connect(app.config['DATABASE_PATH'])
        conn.row_factory = sqlite3.Row
        user = conn.execute(
            "SELECT balance FROM users WHERE username = ?", ('TestUser1',)
        ).fetchone()
        assert user['balance'] == pytest.approx(10000.00 - expected_cost)

        # Verify holding created
        holding = conn.execute(
            "SELECT quantity, avg_purchase_price FROM holdings "
            "WHERE user_id = (SELECT id FROM users WHERE username = 'TestUser1') "
            "AND ore_id = ?",
            (ore_id,)
        ).fetchone()
        assert holding is not None
        assert holding['quantity'] == quantity
        assert holding['avg_purchase_price'] == pytest.approx(10.00)

        # Verify transaction created
        txn = conn.execute(
            "SELECT type, quantity, price_at_trade, total_value FROM transactions "
            "WHERE user_id = (SELECT id FROM users WHERE username = 'TestUser1') "
            "AND ore_id = ?",
            (ore_id,)
        ).fetchone()
        assert txn is not None
        assert txn['type'] == 'buy'
        assert txn['quantity'] == quantity
        assert txn['price_at_trade'] == pytest.approx(10.00)
        assert txn['total_value'] == pytest.approx(expected_cost)
        conn.close()

    def test_insufficient_funds_returns_error_preserves_state(
        self, authenticated_client, app
    ):
        """TC: insufficient funds returns error and preserves state.

        Validates: Requirements 4.2
        """
        ore_id = 9  # Netherite, current_price = 150.00
        # User has 10000.00, buying 100 at 150.00 = 15000.00 > balance
        quantity = 100

        conn = sqlite3.connect(app.config['DATABASE_PATH'])
        conn.row_factory = sqlite3.Row
        pre_balance = conn.execute(
            "SELECT balance FROM users WHERE username = ?", ('TestUser1',)
        ).fetchone()['balance']
        pre_txn_count = conn.execute(
            "SELECT COUNT(*) as cnt FROM transactions"
        ).fetchone()['cnt']
        conn.close()

        response = _buy_ore(authenticated_client, ore_id, str(quantity))
        assert b'Insufficient funds for this trade.' in response.data

        # Verify state unchanged
        conn = sqlite3.connect(app.config['DATABASE_PATH'])
        conn.row_factory = sqlite3.Row
        post_balance = conn.execute(
            "SELECT balance FROM users WHERE username = ?", ('TestUser1',)
        ).fetchone()['balance']
        post_txn_count = conn.execute(
            "SELECT COUNT(*) as cnt FROM transactions"
        ).fetchone()['cnt']
        holding = conn.execute(
            "SELECT * FROM holdings "
            "WHERE user_id = (SELECT id FROM users WHERE username = 'TestUser1') "
            "AND ore_id = ?",
            (ore_id,)
        ).fetchone()
        conn.close()

        assert post_balance == pre_balance
        assert post_txn_count == pre_txn_count
        assert holding is None

    def test_zero_quantity_returns_error(self, authenticated_client):
        """TC: zero quantity returns 'Quantity must be greater than zero.'

        Validates: Requirements 4.3
        """
        ore_id = 1
        response = _buy_ore(authenticated_client, ore_id, '0')
        assert b'Quantity must be greater than zero.' in response.data

    def test_non_numeric_quantity_returns_error(self, authenticated_client):
        """TC: non-numeric quantity returns 'Quantity must be a whole number.'

        Validates: Requirements 4.4
        """
        ore_id = 1
        response = _buy_ore(authenticated_client, ore_id, 'abc')
        assert b'Quantity must be a whole number.' in response.data

    def test_empty_quantity_returns_error(self, authenticated_client):
        """TC: empty quantity returns 'Quantity is required.'

        Validates: Requirements 4.5
        """
        ore_id = 1
        response = _buy_ore(authenticated_client, ore_id, '')
        assert b'Quantity is required.' in response.data

    def test_valid_sell_increases_balance_decreases_holding(
        self, authenticated_client, app
    ):
        """TC: valid sell increases balance, decreases holding, creates transaction.

        Validates: Requirements 4.6
        """
        ore_id = 1  # Coal, current_price = 10.00

        # First buy some ore to have a holding
        _buy_ore(authenticated_client, ore_id, '10')

        conn = sqlite3.connect(app.config['DATABASE_PATH'])
        conn.row_factory = sqlite3.Row
        pre_balance = conn.execute(
            "SELECT balance FROM users WHERE username = ?", ('TestUser1',)
        ).fetchone()['balance']
        conn.close()

        # Now sell 3 units
        sell_quantity = 3
        expected_proceeds = sell_quantity * 10.00
        response = _sell_ore(authenticated_client, ore_id, str(sell_quantity))
        assert response.status_code == 200

        # Verify balance increased
        conn = sqlite3.connect(app.config['DATABASE_PATH'])
        conn.row_factory = sqlite3.Row
        post_balance = conn.execute(
            "SELECT balance FROM users WHERE username = ?", ('TestUser1',)
        ).fetchone()['balance']
        assert post_balance == pytest.approx(pre_balance + expected_proceeds)

        # Verify holding decreased
        holding = conn.execute(
            "SELECT quantity FROM holdings "
            "WHERE user_id = (SELECT id FROM users WHERE username = 'TestUser1') "
            "AND ore_id = ?",
            (ore_id,)
        ).fetchone()
        assert holding['quantity'] == 10 - sell_quantity

        # Verify sell transaction created
        txn = conn.execute(
            "SELECT type, quantity, price_at_trade, total_value FROM transactions "
            "WHERE user_id = (SELECT id FROM users WHERE username = 'TestUser1') "
            "AND ore_id = ? AND type = 'sell'",
            (ore_id,)
        ).fetchone()
        assert txn is not None
        assert txn['quantity'] == sell_quantity
        assert txn['price_at_trade'] == pytest.approx(10.00)
        assert txn['total_value'] == pytest.approx(expected_proceeds)
        conn.close()

    def test_sell_exceeding_holdings_returns_error_preserves_state(
        self, authenticated_client, app
    ):
        """TC: sell exceeding holdings returns error and preserves state.

        Validates: Requirements 4.7
        """
        ore_id = 1  # Coal

        # Buy 5 units first
        _buy_ore(authenticated_client, ore_id, '5')

        conn = sqlite3.connect(app.config['DATABASE_PATH'])
        conn.row_factory = sqlite3.Row
        pre_balance = conn.execute(
            "SELECT balance FROM users WHERE username = ?", ('TestUser1',)
        ).fetchone()['balance']
        pre_holding_qty = conn.execute(
            "SELECT quantity FROM holdings "
            "WHERE user_id = (SELECT id FROM users WHERE username = 'TestUser1') "
            "AND ore_id = ?",
            (ore_id,)
        ).fetchone()['quantity']
        conn.close()

        # Try to sell 10 (more than held)
        response = _sell_ore(authenticated_client, ore_id, '10')
        assert b'You do not have enough of this ore to sell.' in response.data

        # Verify state unchanged
        conn = sqlite3.connect(app.config['DATABASE_PATH'])
        conn.row_factory = sqlite3.Row
        post_balance = conn.execute(
            "SELECT balance FROM users WHERE username = ?", ('TestUser1',)
        ).fetchone()['balance']
        post_holding_qty = conn.execute(
            "SELECT quantity FROM holdings "
            "WHERE user_id = (SELECT id FROM users WHERE username = 'TestUser1') "
            "AND ore_id = ?",
            (ore_id,)
        ).fetchone()['quantity']
        conn.close()

        assert post_balance == pre_balance
        assert post_holding_qty == pre_holding_qty

    def test_sell_entire_holding_deletes_row(self, authenticated_client, app):
        """TC: sell entire holding deletes the holding row.

        Validates: Requirements 4.8
        """
        ore_id = 1  # Coal, current_price = 10.00

        # Buy 5 units
        _buy_ore(authenticated_client, ore_id, '5')

        # Sell all 5 units
        expected_proceeds = 5 * 10.00
        response = _sell_ore(authenticated_client, ore_id, '5')
        assert response.status_code == 200

        # Verify holding row is deleted
        conn = sqlite3.connect(app.config['DATABASE_PATH'])
        conn.row_factory = sqlite3.Row
        holding = conn.execute(
            "SELECT * FROM holdings "
            "WHERE user_id = (SELECT id FROM users WHERE username = 'TestUser1') "
            "AND ore_id = ?",
            (ore_id,)
        ).fetchone()
        assert holding is None

        # Verify balance increased correctly
        user = conn.execute(
            "SELECT balance FROM users WHERE username = ?", ('TestUser1',)
        ).fetchone()
        # Started with 10000, bought 5*10=50, so had 9950, then sold 5*10=50
        assert user['balance'] == pytest.approx(10000.00)
        conn.close()

    def test_buy_additional_ore_recalculates_weighted_average(
        self, authenticated_client, app
    ):
        """TC: buy additional ore recalculates weighted average price.

        Validates: Requirements 4.9
        """
        ore_id = 1  # Coal, current_price = 10.00

        # First buy: 5 units at 10.00
        _buy_ore(authenticated_client, ore_id, '5')

        # Change the ore's current price directly in the DB to simulate price change
        conn = sqlite3.connect(app.config['DATABASE_PATH'])
        conn.execute("UPDATE ores SET current_price = 20.00 WHERE id = ?", (ore_id,))
        conn.commit()
        conn.close()

        # Second buy: 5 units at 20.00
        _buy_ore(authenticated_client, ore_id, '5')

        # Verify weighted average: (5*10 + 5*20) / (5+5) = 150/10 = 15.00
        conn = sqlite3.connect(app.config['DATABASE_PATH'])
        conn.row_factory = sqlite3.Row
        holding = conn.execute(
            "SELECT quantity, avg_purchase_price FROM holdings "
            "WHERE user_id = (SELECT id FROM users WHERE username = 'TestUser1') "
            "AND ore_id = ?",
            (ore_id,)
        ).fetchone()
        conn.close()

        assert holding['quantity'] == 10
        assert holding['avg_purchase_price'] == pytest.approx(15.00)

    def test_simulated_db_error_preserves_pre_trade_state(
        self, authenticated_client, app
    ):
        """TC: simulated DB error mid-transaction preserves pre-trade state.

        Validates: Requirements 4.10
        """
        ore_id = 1  # Coal, current_price = 10.00

        # Record pre-trade state
        conn = sqlite3.connect(app.config['DATABASE_PATH'])
        conn.row_factory = sqlite3.Row
        pre_balance = conn.execute(
            "SELECT balance FROM users WHERE username = ?", ('TestUser1',)
        ).fetchone()['balance']
        pre_txn_count = conn.execute(
            "SELECT COUNT(*) as cnt FROM transactions"
        ).fetchone()['cnt']
        conn.close()

        # Patch the connection's commit method to raise an exception
        with patch('app.database.sqlite3.connect') as mock_connect:
            # We need a more targeted approach: patch the commit on the
            # connection returned by get_db during the confirmed trade.
            pass

        # Better approach: patch the commit on the connection object
        # We mock at the point where db.commit() is called in the trade route
        original_get_db = None

        class FakeConnection:
            """Wraps a real connection but raises on commit."""

            def __init__(self, real_conn):
                self._real = real_conn

            def execute(self, *args, **kwargs):
                return self._real.execute(*args, **kwargs)

            def commit(self):
                raise Exception("Simulated database error")

            def rollback(self):
                return self._real.rollback()

            def __getattr__(self, name):
                return getattr(self._real, name)

        with patch('app.routes.trade.get_db') as mock_get_db:
            # Make get_db return our fake connection that errors on commit
            def side_effect():
                import sqlite3 as sq
                from flask import current_app, g
                if 'db' not in g:
                    g.db = sq.connect(current_app.config['DATABASE_PATH'])
                    g.db.row_factory = sq.Row
                    g.db.execute("PRAGMA journal_mode=WAL")
                    g.db.execute("PRAGMA foreign_keys=ON")
                return FakeConnection(g.db)
            mock_get_db.side_effect = side_effect

            # Attempt a buy - this should fail due to commit error
            response = _buy_ore(authenticated_client, ore_id, '5')

        # Verify flash error message appears
        assert b'An error occurred while processing your trade.' in response.data

        # Verify no state changes persisted
        conn = sqlite3.connect(app.config['DATABASE_PATH'])
        conn.row_factory = sqlite3.Row
        post_balance = conn.execute(
            "SELECT balance FROM users WHERE username = ?", ('TestUser1',)
        ).fetchone()['balance']
        post_txn_count = conn.execute(
            "SELECT COUNT(*) as cnt FROM transactions"
        ).fetchone()['cnt']
        holding = conn.execute(
            "SELECT * FROM holdings "
            "WHERE user_id = (SELECT id FROM users WHERE username = 'TestUser1') "
            "AND ore_id = ?",
            (ore_id,)
        ).fetchone()
        conn.close()

        assert post_balance == pre_balance
        assert post_txn_count == pre_txn_count
        assert holding is None

    def test_negative_quantity_returns_error(self, authenticated_client):
        """TC: negative quantity returns 'Quantity must be greater than zero.'

        Validates: Requirements 4.11
        """
        ore_id = 1
        response = _buy_ore(authenticated_client, ore_id, '-5')
        assert b'Quantity must be greater than zero.' in response.data


# ---------------------------------------------------------------------------
# Property-Based Tests
# ---------------------------------------------------------------------------

from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st


@pytest.mark.trading
class TestTradingProperties:
    """Property-based tests for trading arithmetic correctness."""

    # Feature: orex-test-suite, Property 1: Buy trade arithmetic
    @settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
    @given(quantity=st.integers(min_value=1, max_value=100))
    def test_buy_trade_arithmetic(self, quantity, authenticated_client, app):
        """For any valid buy quantity, balance decreases by quantity * price,
        holding is created with correct quantity and price, and a transaction
        row records the trade.

        **Validates: Requirements 4.1**
        """
        ore_id = 1  # Coal
        fixed_price = 10.00

        # Reset state for each Hypothesis example: restore balance, clear
        # holdings and transactions so each iteration starts clean.
        conn = sqlite3.connect(app.config['DATABASE_PATH'])
        conn.execute(
            "UPDATE users SET balance = 10000.00 WHERE username = ?",
            ('TestUser1',),
        )
        conn.execute(
            "DELETE FROM holdings WHERE user_id = "
            "(SELECT id FROM users WHERE username = 'TestUser1')"
        )
        conn.execute(
            "DELETE FROM transactions WHERE user_id = "
            "(SELECT id FROM users WHERE username = 'TestUser1')"
        )
        # Set Coal's price to a known fixed value for predictable arithmetic
        conn.execute(
            "UPDATE ores SET current_price = ? WHERE id = ?",
            (fixed_price, ore_id),
        )
        conn.commit()
        conn.close()

        # Record pre-trade balance
        conn = sqlite3.connect(app.config['DATABASE_PATH'])
        conn.row_factory = sqlite3.Row
        pre_balance = conn.execute(
            "SELECT balance FROM users WHERE username = ?", ('TestUser1',)
        ).fetchone()['balance']
        conn.close()

        expected_cost = quantity * fixed_price

        # Execute buy
        response = _buy_ore(authenticated_client, ore_id, str(quantity))
        assert response.status_code == 200

        # Verify balance decreased by exactly quantity * price
        conn = sqlite3.connect(app.config['DATABASE_PATH'])
        conn.row_factory = sqlite3.Row
        post_balance = conn.execute(
            "SELECT balance FROM users WHERE username = ?", ('TestUser1',)
        ).fetchone()['balance']
        assert post_balance == pytest.approx(pre_balance - expected_cost)

        # Verify holding created with correct quantity and price
        holding = conn.execute(
            "SELECT quantity, avg_purchase_price FROM holdings "
            "WHERE user_id = (SELECT id FROM users WHERE username = 'TestUser1') "
            "AND ore_id = ?",
            (ore_id,),
        ).fetchone()
        assert holding is not None
        assert holding['quantity'] == quantity
        assert holding['avg_purchase_price'] == pytest.approx(fixed_price)

        # Verify transaction row records the trade
        txn = conn.execute(
            "SELECT type, quantity, price_at_trade, total_value FROM transactions "
            "WHERE user_id = (SELECT id FROM users WHERE username = 'TestUser1') "
            "AND ore_id = ? AND type = 'buy'",
            (ore_id,),
        ).fetchone()
        assert txn is not None
        assert txn['type'] == 'buy'
        assert txn['quantity'] == quantity
        assert txn['price_at_trade'] == pytest.approx(fixed_price)
        assert txn['total_value'] == pytest.approx(expected_cost)
        conn.close()

    # Feature: orex-test-suite, Property 2: Sell trade arithmetic
    @settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
    @given(sell_quantity=st.integers(min_value=1, max_value=100))
    def test_sell_trade_arithmetic(self, sell_quantity, authenticated_client, app):
        """For any valid sell quantity within held amount, balance increases by
        quantity * current_price, holding quantity decreases by sold amount,
        and a transaction row records the trade.

        **Validates: Requirements 4.6**
        """
        ore_id = 1  # Coal
        fixed_price = 10.00
        buy_quantity = 100  # Buy 100 units to establish a holding

        # Reset state for this iteration: clear holdings and transactions,
        # reset user balance, and set ore price to known value
        conn = sqlite3.connect(app.config['DATABASE_PATH'])
        user_id_row = conn.execute(
            "SELECT id FROM users WHERE username = ?", ('TestUser1',)
        ).fetchone()
        if user_id_row:
            user_id = user_id_row[0]
            conn.execute(
                "DELETE FROM holdings WHERE user_id = ?", (user_id,)
            )
            conn.execute(
                "DELETE FROM transactions WHERE user_id = ?", (user_id,)
            )
            conn.execute(
                "UPDATE users SET balance = 10000.00 WHERE id = ?", (user_id,)
            )
        conn.execute(
            "UPDATE ores SET current_price = ? WHERE id = ?",
            (fixed_price, ore_id),
        )
        conn.commit()
        conn.close()

        # Buy 100 units to establish a holding
        response = _buy_ore(authenticated_client, ore_id, str(buy_quantity))
        assert response.status_code == 200

        # Record pre-sell state
        conn = sqlite3.connect(app.config['DATABASE_PATH'])
        conn.row_factory = sqlite3.Row
        pre_balance = conn.execute(
            "SELECT balance FROM users WHERE username = ?", ('TestUser1',)
        ).fetchone()['balance']
        pre_holding_qty = conn.execute(
            "SELECT quantity FROM holdings "
            "WHERE user_id = (SELECT id FROM users WHERE username = 'TestUser1') "
            "AND ore_id = ?",
            (ore_id,),
        ).fetchone()['quantity']
        conn.close()

        expected_proceeds = sell_quantity * fixed_price

        # Execute sell
        response = _sell_ore(authenticated_client, ore_id, str(sell_quantity))
        assert response.status_code == 200

        # Verify balance increased by exactly sell_quantity * current_price
        conn = sqlite3.connect(app.config['DATABASE_PATH'])
        conn.row_factory = sqlite3.Row
        post_balance = conn.execute(
            "SELECT balance FROM users WHERE username = ?", ('TestUser1',)
        ).fetchone()['balance']
        assert post_balance == pytest.approx(pre_balance + expected_proceeds)

        # Verify holding quantity decreased by sold amount
        holding = conn.execute(
            "SELECT quantity FROM holdings "
            "WHERE user_id = (SELECT id FROM users WHERE username = 'TestUser1') "
            "AND ore_id = ?",
            (ore_id,),
        ).fetchone()
        if sell_quantity < buy_quantity:
            assert holding is not None
            assert holding['quantity'] == pre_holding_qty - sell_quantity
        else:
            # If sold entire holding, row may be deleted
            assert holding is None or holding['quantity'] == 0

        # Verify sell transaction row records the trade
        txn = conn.execute(
            "SELECT type, quantity, price_at_trade, total_value FROM transactions "
            "WHERE user_id = (SELECT id FROM users WHERE username = 'TestUser1') "
            "AND ore_id = ? AND type = 'sell'",
            (ore_id,),
        ).fetchone()
        assert txn is not None
        assert txn['type'] == 'sell'
        assert txn['quantity'] == sell_quantity
        assert txn['price_at_trade'] == pytest.approx(fixed_price)
        assert txn['total_value'] == pytest.approx(expected_proceeds)
        conn.close()

    # Feature: orex-test-suite, Property 3: Invalid trade rejection preserves state
    @settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
    @given(
        buy_quantity=st.integers(min_value=1001, max_value=5000),
        sell_quantity=st.integers(min_value=6, max_value=100),
    )
    def test_invalid_trade_rejection_preserves_state(
        self, buy_quantity, sell_quantity, authenticated_client, app
    ):
        """For any trade attempt that violates a precondition (buy with
        insufficient funds, sell with insufficient holdings), balance,
        holdings, and transaction count remain unchanged.

        **Validates: Requirements 4.2, 4.7**
        """
        ore_id = 1  # Coal
        fixed_price = 10.00

        # Reset state for this iteration: clear holdings and transactions,
        # reset user balance, and set ore price to known value
        conn = sqlite3.connect(app.config['DATABASE_PATH'])
        user_id_row = conn.execute(
            "SELECT id FROM users WHERE username = ?", ('TestUser1',)
        ).fetchone()
        if user_id_row:
            user_id = user_id_row[0]
            conn.execute(
                "DELETE FROM holdings WHERE user_id = ?", (user_id,)
            )
            conn.execute(
                "DELETE FROM transactions WHERE user_id = ?", (user_id,)
            )
            conn.execute(
                "UPDATE users SET balance = 10000.00 WHERE id = ?", (user_id,)
            )
        conn.execute(
            "UPDATE ores SET current_price = ? WHERE id = ?",
            (fixed_price, ore_id),
        )
        conn.commit()
        conn.close()

        # --- Invalid buy: quantity * price > balance (10000.00) ---
        # buy_quantity >= 1001 at $10 = $10010+ which exceeds $10000 balance
        conn = sqlite3.connect(app.config['DATABASE_PATH'])
        conn.row_factory = sqlite3.Row
        pre_balance = conn.execute(
            "SELECT balance FROM users WHERE username = ?", ('TestUser1',)
        ).fetchone()['balance']
        pre_txn_count = conn.execute(
            "SELECT COUNT(*) as cnt FROM transactions"
        ).fetchone()['cnt']
        pre_holding = conn.execute(
            "SELECT * FROM holdings "
            "WHERE user_id = (SELECT id FROM users WHERE username = 'TestUser1') "
            "AND ore_id = ?",
            (ore_id,),
        ).fetchone()
        conn.close()

        _buy_ore(authenticated_client, ore_id, str(buy_quantity))

        # Verify state unchanged after invalid buy
        conn = sqlite3.connect(app.config['DATABASE_PATH'])
        conn.row_factory = sqlite3.Row
        post_balance = conn.execute(
            "SELECT balance FROM users WHERE username = ?", ('TestUser1',)
        ).fetchone()['balance']
        post_txn_count = conn.execute(
            "SELECT COUNT(*) as cnt FROM transactions"
        ).fetchone()['cnt']
        post_holding = conn.execute(
            "SELECT * FROM holdings "
            "WHERE user_id = (SELECT id FROM users WHERE username = 'TestUser1') "
            "AND ore_id = ?",
            (ore_id,),
        ).fetchone()
        conn.close()

        assert post_balance == pre_balance
        assert post_txn_count == pre_txn_count
        assert post_holding == pre_holding

        # --- Invalid sell: sell more than held ---
        # First buy 5 units to establish a holding
        _buy_ore(authenticated_client, ore_id, '5')

        # Record state after the valid buy
        conn = sqlite3.connect(app.config['DATABASE_PATH'])
        conn.row_factory = sqlite3.Row
        pre_sell_balance = conn.execute(
            "SELECT balance FROM users WHERE username = ?", ('TestUser1',)
        ).fetchone()['balance']
        pre_sell_txn_count = conn.execute(
            "SELECT COUNT(*) as cnt FROM transactions"
        ).fetchone()['cnt']
        pre_sell_holding = conn.execute(
            "SELECT quantity FROM holdings "
            "WHERE user_id = (SELECT id FROM users WHERE username = 'TestUser1') "
            "AND ore_id = ?",
            (ore_id,),
        ).fetchone()
        conn.close()

        # sell_quantity >= 6 which exceeds the 5 units held
        _sell_ore(authenticated_client, ore_id, str(sell_quantity))

        # Verify state unchanged after invalid sell
        conn = sqlite3.connect(app.config['DATABASE_PATH'])
        conn.row_factory = sqlite3.Row
        post_sell_balance = conn.execute(
            "SELECT balance FROM users WHERE username = ?", ('TestUser1',)
        ).fetchone()['balance']
        post_sell_txn_count = conn.execute(
            "SELECT COUNT(*) as cnt FROM transactions"
        ).fetchone()['cnt']
        post_sell_holding = conn.execute(
            "SELECT quantity FROM holdings "
            "WHERE user_id = (SELECT id FROM users WHERE username = 'TestUser1') "
            "AND ore_id = ?",
            (ore_id,),
        ).fetchone()
        conn.close()

        assert post_sell_balance == pre_sell_balance
        assert post_sell_txn_count == pre_sell_txn_count
        assert post_sell_holding['quantity'] == pre_sell_holding['quantity']


# ---------------------------------------------------------------------------
# Property-Based Tests (Hypothesis)
# ---------------------------------------------------------------------------

import os
import sqlite3 as _sqlite3

from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st

from conftest import get_csrf_token, register_user


# Feature: orex-test-suite, Property 4: Weighted average price formula
class TestWeightedAveragePriceProperty:
    """Property test verifying the weighted average price formula.

    **Validates: Requirements 4.9**
    """

    @settings(
        max_examples=100,
        deadline=None,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    @given(
        old_qty=st.integers(min_value=1, max_value=50),
        new_qty=st.integers(min_value=1, max_value=50),
    )
    def test_weighted_average_price_formula(
        self, old_qty, new_qty, authenticated_client, app
    ):
        """For any (old_qty, new_qty) buys at two different prices,
        avg_purchase_price == (old_qty * price1 + new_qty * price2) / (old_qty + new_qty)
        and holding quantity == old_qty + new_qty.

        **Validates: Requirements 4.9**
        """
        ore_id = 1  # Coal
        price1 = 10.00
        price2 = 20.00

        # Reset DB state for each Hypothesis iteration
        db_path = app.config['DATABASE_PATH']
        src_dir = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'src'
        )
        schema_path = os.path.join(src_dir, 'schema.sql')
        seed_path = os.path.join(src_dir, 'seed.sql')

        conn = _sqlite3.connect(db_path)
        conn.execute("PRAGMA foreign_keys=OFF")
        for table in ('price_history', 'transactions', 'holdings', 'ores', 'users'):
            conn.execute(f'DROP TABLE IF EXISTS {table}')
        with open(schema_path, 'r') as f:
            conn.executescript(f.read())
        with open(seed_path, 'r') as f:
            conn.executescript(f.read())
        conn.close()

        # Re-register and login the test user for this iteration
        register_user(authenticated_client, 'TestUser1', 'Password123!')

        # Ensure Coal's price is price1 for the first buy
        conn = _sqlite3.connect(db_path)
        conn.execute(
            "UPDATE ores SET current_price = ? WHERE id = ?", (price1, ore_id)
        )
        conn.commit()
        conn.close()

        # First buy: old_qty units at price1
        _buy_ore(authenticated_client, ore_id, str(old_qty))

        # Change Coal's price to price2 for the second buy
        conn = _sqlite3.connect(db_path)
        conn.execute(
            "UPDATE ores SET current_price = ? WHERE id = ?", (price2, ore_id)
        )
        conn.commit()
        conn.close()

        # Second buy: new_qty units at price2
        _buy_ore(authenticated_client, ore_id, str(new_qty))

        # Verify weighted average formula
        expected_avg = (old_qty * price1 + new_qty * price2) / (old_qty + new_qty)

        conn = _sqlite3.connect(db_path)
        conn.row_factory = _sqlite3.Row
        holding = conn.execute(
            "SELECT quantity, avg_purchase_price FROM holdings "
            "WHERE user_id = (SELECT id FROM users WHERE username = 'TestUser1') "
            "AND ore_id = ?",
            (ore_id,),
        ).fetchone()
        conn.close()

        assert holding is not None
        assert holding['quantity'] == old_qty + new_qty
        assert holding['avg_purchase_price'] == pytest.approx(expected_avg, rel=1e-6)


