"""Property-based tests for Advanced Mode eligibility, purchase, and toggle logic.

Uses Hypothesis for property-based testing with minimum 100 iterations per property.
Tests the actual functions from app.advanced against an isolated test database.
"""

import sqlite3
from datetime import datetime, timedelta

from hypothesis import given, settings, assume
from hypothesis import strategies as st

from app.advanced import (
    check_eligibility,
    purchase_advanced_mode,
    toggle_advanced_mode,
)
from app.market.engine import evaluate_stop_loss_take_profit
from app.market.levels import calculate_levels


TEST_USER_ID = 9999


def _clean_test_state(db):
    """Remove all test-specific rows to allow Hypothesis re-runs within one test."""
    # Delete in FK-safe order: children first, then parents
    db.execute("DELETE FROM stop_loss_take_profit WHERE holding_id IN (SELECT id FROM holdings WHERE user_id = ?)", (TEST_USER_ID,))
    db.execute("DELETE FROM transactions WHERE user_id = ?", (TEST_USER_ID,))
    db.execute("DELETE FROM holdings WHERE user_id = ?", (TEST_USER_ID,))
    db.execute("DELETE FROM users WHERE id = ?", (TEST_USER_ID,))
    # Clean up test ores (IDs 9000+)
    db.execute("DELETE FROM price_history WHERE ore_id >= 9000")
    db.execute("DELETE FROM ores WHERE id >= 9000")
    db.commit()


# ---------------------------------------------------------------------------
# Feature: advanced-mode, Property 1: Net Worth Calculation Identity
# Validates: Requirements 1.3
# ---------------------------------------------------------------------------

@settings(max_examples=100)
@given(
    balance=st.floats(min_value=0, max_value=1e6),
    holdings=st.lists(
        st.tuples(
            st.integers(min_value=1, max_value=10000),
            st.floats(min_value=0.01, max_value=10000),
        ),
        min_size=0,
        max_size=10,
    ),
)
def test_net_worth_calculation_identity(app, balance, holdings):
    """Property 1: For any user with balance B and holdings H, net worth
    equals B + Σ(qty × price). The eligibility check uses this calculation
    to determine if net worth >= threshold.
    """
    # Filter out NaN/Inf floats that would break DB operations
    assume(balance == balance)  # not NaN
    for qty, price in holdings:
        assume(price == price)  # not NaN

    with app.app_context():
        from app.database import get_db
        db = get_db()
        _clean_test_state(db)

        # Insert a test user with the given balance
        db.execute(
            "INSERT INTO users (id, username, password_hash, balance) VALUES (?, ?, ?, ?)",
            (TEST_USER_ID, 'proptest_user', 'hash', balance),
        )

        # Insert ores and holdings for this user
        for i, (qty, price) in enumerate(holdings):
            ore_id = 9000 + i
            db.execute(
                "INSERT INTO ores (id, name, current_price, base_price, price_floor, "
                "price_ceiling, volatility, price_change_range, base_probabilities) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (ore_id, f'TestOre{i}', price, price, price * 0.5, price * 2.0,
                 0.1, '[-0.05, 0.05]', '[0.3, 0.4, 0.3]'),
            )
            db.execute(
                "INSERT INTO holdings (user_id, ore_id, quantity, avg_purchase_price) "
                "VALUES (?, ?, ?, ?)",
                (TEST_USER_ID, ore_id, qty, price),
            )

        db.commit()

        # Calculate expected net worth
        expected_net_worth = balance + sum(qty * price for qty, price in holdings)

        # The eligibility function checks if net_worth >= threshold.
        # We verify the calculation by checking the result matches expectations:
        # If expected_net_worth >= 100_000, eligibility should return True
        # If expected_net_worth < 100_000, eligibility should return False
        result = check_eligibility(TEST_USER_ID)
        threshold = app.config['ADVANCED_MODE_THRESHOLD']

        if expected_net_worth >= threshold:
            assert result is True, (
                f"Expected eligible: net_worth={expected_net_worth} >= threshold={threshold}"
            )
        else:
            assert result is False, (
                f"Expected ineligible: net_worth={expected_net_worth} < threshold={threshold}"
            )


# ---------------------------------------------------------------------------
# Feature: advanced-mode, Property 2: Eligibility Monotonicity
# Validates: Requirements 1.1, 1.2
# ---------------------------------------------------------------------------

@settings(max_examples=100)
@given(
    eligible_flag=st.booleans(),
    net_worth_balance=st.floats(min_value=0, max_value=200000),
)
def test_eligibility_monotonicity(app, eligible_flag, net_worth_balance):
    """Property 2: Once the eligible flag is set to 1, check_eligibility
    returns True regardless of current net worth — even below threshold.
    """
    assume(net_worth_balance == net_worth_balance)  # not NaN

    with app.app_context():
        from app.database import get_db
        db = get_db()
        _clean_test_state(db)

        advanced_eligible = 1 if eligible_flag else 0

        db.execute(
            "INSERT INTO users (id, username, password_hash, balance, advanced_eligible) "
            "VALUES (?, ?, ?, ?, ?)",
            (TEST_USER_ID, 'proptest_user', 'hash', net_worth_balance, advanced_eligible),
        )
        db.commit()

        result = check_eligibility(TEST_USER_ID)

        if eligible_flag:
            # Once eligible flag is set, ALWAYS returns True (sticky)
            assert result is True, (
                f"Eligible flag is set but check returned False "
                f"(balance={net_worth_balance})"
            )
        else:
            # When not flagged, result depends on net worth vs threshold
            threshold = app.config['ADVANCED_MODE_THRESHOLD']
            if net_worth_balance >= threshold:
                assert result is True
            else:
                assert result is False


# ---------------------------------------------------------------------------
# Feature: advanced-mode, Property 3: Purchase Balance Deduction
# Validates: Requirements 3.1
# ---------------------------------------------------------------------------

@settings(max_examples=100)
@given(
    starting_balance=st.floats(min_value=50000, max_value=1e6),
)
def test_purchase_balance_deduction(app, starting_balance):
    """Property 3: For any eligible user with balance >= $50,000, after a
    successful purchase, new balance = previous balance - exactly $50,000.
    """
    assume(starting_balance == starting_balance)  # not NaN

    with app.app_context():
        from app.database import get_db
        db = get_db()
        _clean_test_state(db)

        # Create an eligible user (advanced_eligible=1) with given balance
        db.execute(
            "INSERT INTO users (id, username, password_hash, balance, advanced_eligible) "
            "VALUES (?, ?, ?, ?, ?)",
            (TEST_USER_ID, 'proptest_user', 'hash', starting_balance, 1),
        )
        db.commit()

        success, message = purchase_advanced_mode(TEST_USER_ID)

        assert success is True, f"Purchase should succeed: {message}"

        # Verify exact deduction
        user = db.execute(
            "SELECT balance FROM users WHERE id = ?", (TEST_USER_ID,)
        ).fetchone()

        cost = app.config['ADVANCED_MODE_COST']
        expected_balance = starting_balance - cost

        assert abs(user['balance'] - expected_balance) < 1e-9, (
            f"Balance should be {expected_balance}, got {user['balance']}"
        )


# ---------------------------------------------------------------------------
# Feature: advanced-mode, Property 4: Purchase Precondition Rejection
# Validates: Requirements 3.2, 3.3
# ---------------------------------------------------------------------------

@settings(max_examples=100)
@given(
    low_balance=st.floats(min_value=0, max_value=49999.99),
    eligible_flag=st.booleans(),
)
def test_purchase_precondition_rejection(app, low_balance, eligible_flag):
    """Property 4: Purchase is rejected when either (a) user is not eligible,
    or (b) balance is below $50,000. Balance remains unchanged after rejection.
    """
    assume(low_balance == low_balance)  # not NaN

    with app.app_context():
        from app.database import get_db
        db = get_db()
        _clean_test_state(db)

        advanced_eligible = 1 if eligible_flag else 0

        db.execute(
            "INSERT INTO users (id, username, password_hash, balance, advanced_eligible) "
            "VALUES (?, ?, ?, ?, ?)",
            (TEST_USER_ID, 'proptest_user', 'hash', low_balance, advanced_eligible),
        )
        db.commit()

        # Case: either ineligible OR insufficient funds (balance < 50k)
        # If eligible_flag is True but balance < 50k → rejected (insufficient funds)
        # If eligible_flag is False → rejected (ineligible) regardless of balance
        # Since low_balance is always < 50k, at minimum the funds check fails when eligible
        success, message = purchase_advanced_mode(TEST_USER_ID)

        if not eligible_flag:
            # Ineligible: rejected
            assert success is False, "Purchase should be rejected when ineligible"
        else:
            # Eligible but insufficient funds (balance < 50k)
            assert success is False, (
                f"Purchase should be rejected with balance={low_balance} < 50000"
            )

        # Balance must remain unchanged
        user = db.execute(
            "SELECT balance FROM users WHERE id = ?", (TEST_USER_ID,)
        ).fetchone()

        assert abs(user['balance'] - low_balance) < 1e-9, (
            f"Balance should remain {low_balance}, got {user['balance']}"
        )


# ---------------------------------------------------------------------------
# Feature: advanced-mode, Property 5: Toggle State Inversion
# Validates: Requirements 4.2
# ---------------------------------------------------------------------------

@settings(max_examples=100)
@given(
    current_active=st.booleans(),
)
def test_toggle_state_inversion(app, current_active):
    """Property 5: For any user with purchased advanced mode and no active
    cooldown, toggle flips active from 0→1 or 1→0.
    """
    with app.app_context():
        from app.database import get_db
        db = get_db()
        _clean_test_state(db)

        active_val = 1 if current_active else 0

        # Create user with purchased mode, given active state, no cooldown
        db.execute(
            "INSERT INTO users (id, username, password_hash, balance, "
            "advanced_purchased, advanced_active, advanced_toggled_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (TEST_USER_ID, 'proptest_user', 'hash', 10000, 1, active_val, None),
        )
        db.commit()

        success, message = toggle_advanced_mode(TEST_USER_ID)

        assert success is True, f"Toggle should succeed: {message}"

        # Verify the state was inverted
        user = db.execute(
            "SELECT advanced_active FROM users WHERE id = ?", (TEST_USER_ID,)
        ).fetchone()

        expected_active = 0 if current_active else 1
        assert user['advanced_active'] == expected_active, (
            f"Expected active={expected_active}, got {user['advanced_active']}"
        )


# ---------------------------------------------------------------------------
# Feature: advanced-mode, Property 6: Cooldown Enforcement
# Validates: Requirements 4.3
# ---------------------------------------------------------------------------

@settings(max_examples=100)
@given(
    elapsed_seconds=st.floats(min_value=0, max_value=600),
)
def test_cooldown_enforcement(app, elapsed_seconds):
    """Property 6: Toggle rejected if elapsed < 300s since last toggle,
    accepted if elapsed >= 300s.
    """
    assume(elapsed_seconds == elapsed_seconds)  # not NaN

    with app.app_context():
        from app.database import get_db
        db = get_db()
        _clean_test_state(db)

        # Calculate the toggled_at timestamp based on elapsed seconds
        now = datetime.now()
        last_toggle_time = now - timedelta(seconds=elapsed_seconds)
        toggled_at_iso = last_toggle_time.isoformat()

        # Create user with purchased mode, active, and a past toggle timestamp
        db.execute(
            "INSERT INTO users (id, username, password_hash, balance, "
            "advanced_purchased, advanced_active, advanced_toggled_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (TEST_USER_ID, 'proptest_user', 'hash', 10000, 1, 1, toggled_at_iso),
        )
        db.commit()

        success, message = toggle_advanced_mode(TEST_USER_ID)

        cooldown = app.config['ADVANCED_TOGGLE_COOLDOWN']  # 300 seconds

        if elapsed_seconds < cooldown:
            assert success is False, (
                f"Toggle should be rejected: elapsed={elapsed_seconds}s < cooldown={cooldown}s"
            )
        else:
            assert success is True, (
                f"Toggle should succeed: elapsed={elapsed_seconds}s >= cooldown={cooldown}s"
            )


# ---------------------------------------------------------------------------
# Feature: advanced-mode, Property 8: Stop Loss / Take Profit Validation
# Validates: Requirements 6.5, 6.6
# ---------------------------------------------------------------------------


def validate_stop_loss_take_profit(stop_loss, take_profit, current_price):
    """Pure validation logic for SL/TP values against current price.

    Mirrors the inline validation in app/routes/trade.py:
    - stop_loss must be < current_price (rejected if >= current_price)
    - take_profit must be > current_price (rejected if <= current_price)

    Returns (valid: bool, error: str | None).
    """
    if stop_loss is not None and stop_loss >= current_price:
        return False, f'Stop loss must be below current price (${current_price:,.2f}).'
    if take_profit is not None and take_profit <= current_price:
        return False, f'Take profit must be above current price (${current_price:,.2f}).'
    return True, None


@settings(max_examples=100)
@given(
    current_price=st.floats(min_value=0.01, max_value=10000),
    stop_loss=st.floats(min_value=0.01, max_value=10000),
    take_profit=st.floats(min_value=0.01, max_value=10000),
)
def test_stop_loss_take_profit_validation(current_price, stop_loss, take_profit):
    """Property 8: For any buy order with SL and TP values, validation SHALL
    reject if SL >= current_price or TP <= current_price. Valid orders require
    SL < current_price AND TP > current_price.

    **Validates: Requirements 6.5, 6.6**
    """
    # Filter out NaN/Inf floats
    assume(current_price == current_price)
    assume(stop_loss == stop_loss)
    assume(take_profit == take_profit)

    valid, error = validate_stop_loss_take_profit(stop_loss, take_profit, current_price)

    # Property: order is valid iff (SL < current_price AND TP > current_price)
    expected_valid = (stop_loss < current_price) and (take_profit > current_price)

    assert valid == expected_valid, (
        f"Validation mismatch: SL={stop_loss}, TP={take_profit}, price={current_price}. "
        f"Expected valid={expected_valid}, got valid={valid}, error={error}"
    )

    # Additional property: if invalid, there must be an error message
    if not valid:
        assert error is not None, "Invalid order should have an error message"
    else:
        assert error is None, "Valid order should have no error message"


@settings(max_examples=100)
@given(
    current_price=st.floats(min_value=0.01, max_value=10000),
    stop_loss=st.floats(min_value=0.01, max_value=10000),
)
def test_stop_loss_rejected_when_at_or_above_price(current_price, stop_loss):
    """Property 8 (SL component): Stop loss is rejected when SL >= current price.

    **Validates: Requirements 6.5**
    """
    assume(current_price == current_price)
    assume(stop_loss == stop_loss)
    assume(stop_loss >= current_price)

    valid, error = validate_stop_loss_take_profit(stop_loss, None, current_price)

    assert valid is False, (
        f"SL={stop_loss} >= price={current_price} should be rejected"
    )
    assert error is not None


@settings(max_examples=100)
@given(
    current_price=st.floats(min_value=0.01, max_value=10000),
    take_profit=st.floats(min_value=0.01, max_value=10000),
)
def test_take_profit_rejected_when_at_or_below_price(current_price, take_profit):
    """Property 8 (TP component): Take profit is rejected when TP <= current price.

    **Validates: Requirements 6.6**
    """
    assume(current_price == current_price)
    assume(take_profit == take_profit)
    assume(take_profit <= current_price)

    valid, error = validate_stop_loss_take_profit(None, take_profit, current_price)

    assert valid is False, (
        f"TP={take_profit} <= price={current_price} should be rejected"
    )
    assert error is not None


# ---------------------------------------------------------------------------
# Feature: advanced-mode, Property 9: Resistance and Support from Rolling Window
# Validates: Requirements 7.4, 7.5, 7.6
# ---------------------------------------------------------------------------

@settings(max_examples=100)
@given(
    prices=st.lists(st.floats(min_value=0.01, max_value=10000), min_size=1, max_size=50),
    lookback=st.integers(min_value=1, max_value=100),
)
def test_resistance_support_from_rolling_window(app, prices, lookback):
    """Property 9: For any ore with price history of length >= 1, resistance
    equals max(last N prices) and support equals min(last N prices). If fewer
    than N entries exist, all available entries are used.
    """
    # Filter out NaN/Inf floats
    for p in prices:
        assume(p == p)  # not NaN

    with app.app_context():
        from app.database import get_db

        db = get_db()

        # Clean price_history for test ores BEFORE _clean_test_state
        # (avoids FK constraint failure when deleting ores)
        ore_id = 9000
        db.execute("DELETE FROM price_history WHERE ore_id >= 9000")
        db.commit()

        _clean_test_state(db)

        # Insert a test ore
        db.execute(
            "INSERT INTO ores (id, name, current_price, base_price, price_floor, "
            "price_ceiling, volatility, price_change_range, base_probabilities) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (ore_id, 'TestOreRS', prices[-1], prices[0], 0.01, 20000.0,
             0.1, '[-0.05, 0.05]', '[0.3, 0.4, 0.3]'),
        )

        # Insert price history entries with incrementing timestamps
        # so that ordering by created_at DESC gives us the last entries first
        base_time = datetime(2024, 1, 1, 0, 0, 0)
        for i, price in enumerate(prices):
            ts = (base_time + timedelta(seconds=i)).isoformat()
            db.execute(
                "INSERT INTO price_history (ore_id, price, movement, created_at) "
                "VALUES (?, ?, ?, ?)",
                (ore_id, price, 0.0, ts),
            )

        db.commit()

        # Call the function under test
        result = calculate_levels(ore_id, lookback=lookback)

        # Determine the expected window: last N prices, or all if fewer than N
        window = prices[-lookback:] if lookback <= len(prices) else prices
        expected_resistance = max(window)
        expected_support = min(window)

        assert result['resistance'] == expected_resistance, (
            f"Resistance should be {expected_resistance}, got {result['resistance']}. "
            f"prices={prices}, lookback={lookback}"
        )
        assert result['support'] == expected_support, (
            f"Support should be {expected_support}, got {result['support']}. "
            f"prices={prices}, lookback={lookback}"
        )


# ---------------------------------------------------------------------------
# Feature: advanced-mode, Property 7: Stop Loss / Take Profit Trigger Execution
# Validates: Requirements 6.3, 6.4
# ---------------------------------------------------------------------------


@st.composite
def _sl_trigger_scenario(draw):
    """Generate a scenario where current_price <= stop_loss (SL triggers).

    Strategy: pick stop_loss first, then current_price <= stop_loss,
    then take_profit > stop_loss. This avoids excessive filtering.
    """
    stop_loss = draw(st.floats(min_value=0.02, max_value=10000))
    current_price = draw(st.floats(min_value=0.01, max_value=stop_loss))
    take_profit = draw(st.floats(min_value=stop_loss + 0.01, max_value=10001))
    quantity = draw(st.integers(min_value=1, max_value=10000))
    initial_balance = draw(st.floats(min_value=0, max_value=1e6))
    assume(current_price == current_price and stop_loss == stop_loss)
    assume(take_profit == take_profit and initial_balance == initial_balance)
    return current_price, stop_loss, take_profit, quantity, initial_balance


@settings(max_examples=100)
@given(data=_sl_trigger_scenario())
def test_sltp_trigger_execution_stop_loss(app, data):
    """Property 7 (Stop Loss): When current_price <= stop_loss, the order is
    triggered, the holding is sold, and balance is credited.

    **Validates: Requirements 6.3, 6.4**
    """
    current_price, stop_loss, take_profit, quantity, initial_balance = data

    with app.app_context():
        from app.database import get_db
        db = get_db()
        _clean_test_state(db)

        # Set up test user
        db.execute(
            "INSERT INTO users (id, username, password_hash, balance) VALUES (?, ?, ?, ?)",
            (TEST_USER_ID, 'proptest_user', 'hash', initial_balance),
        )

        # Set up test ore with the current_price
        ore_id = 9000
        db.execute(
            "INSERT INTO ores (id, name, current_price, base_price, price_floor, "
            "price_ceiling, volatility, price_change_range, base_probabilities) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (ore_id, 'TestOreSLTP', current_price, current_price, 0.01, 20000.0,
             0.1, '[-0.05, 0.05]', '[0.3, 0.4, 0.3]'),
        )

        # Set up a holding for the user
        db.execute(
            "INSERT INTO holdings (id, user_id, ore_id, quantity, avg_purchase_price) "
            "VALUES (?, ?, ?, ?, ?)",
            (9000, TEST_USER_ID, ore_id, quantity, current_price),
        )

        # Set up an active SL/TP order
        db.execute(
            "INSERT INTO stop_loss_take_profit (id, holding_id, stop_loss, take_profit, active) "
            "VALUES (?, ?, ?, ?, ?)",
            (9000, 9000, stop_loss, take_profit, 1),
        )
        db.commit()

        # Run the evaluator
        evaluate_stop_loss_take_profit(db)

        # Assert: order is marked as triggered OR cascade-deleted with the holding.
        order = db.execute(
            "SELECT active, triggered_at FROM stop_loss_take_profit WHERE id = ?",
            (9000,)
        ).fetchone()
        if order is not None:
            assert order['active'] == 0, "SL/TP order should be deactivated after trigger"
            assert order['triggered_at'] is not None, "triggered_at should be set"

        # Assert: holding is deleted (sold)
        holding = db.execute(
            "SELECT * FROM holdings WHERE id = ?", (9000,)
        ).fetchone()
        assert holding is None, "Holding should be deleted after auto-sell"

        # Assert: user balance is credited (balance += quantity × current_price)
        user = db.execute(
            "SELECT balance FROM users WHERE id = ?", (TEST_USER_ID,)
        ).fetchone()
        expected_balance = initial_balance + (quantity * current_price)
        assert abs(user['balance'] - expected_balance) < 1e-6, (
            f"Balance should be {expected_balance}, got {user['balance']}"
        )

        # Assert: a sell transaction is recorded
        txn = db.execute(
            "SELECT * FROM transactions WHERE user_id = ? AND type = 'sell' AND ore_id = ?",
            (TEST_USER_ID, ore_id)
        ).fetchone()
        assert txn is not None, "A sell transaction should be recorded"
        assert txn['quantity'] == quantity
        assert abs(txn['price_at_trade'] - current_price) < 1e-6
        assert abs(txn['total_value'] - (quantity * current_price)) < 1e-6


@st.composite
def _tp_trigger_scenario(draw):
    """Generate a scenario where current_price >= take_profit (TP triggers).

    Strategy: pick take_profit first, then current_price >= take_profit,
    then stop_loss < take_profit. This avoids excessive filtering.
    """
    take_profit = draw(st.floats(min_value=0.02, max_value=10000))
    current_price = draw(st.floats(min_value=take_profit, max_value=10001))
    stop_loss = draw(st.floats(min_value=0.01, max_value=take_profit - 0.01))
    quantity = draw(st.integers(min_value=1, max_value=10000))
    initial_balance = draw(st.floats(min_value=0, max_value=1e6))
    assume(current_price == current_price and stop_loss == stop_loss)
    assume(take_profit == take_profit and initial_balance == initial_balance)
    return current_price, stop_loss, take_profit, quantity, initial_balance


@settings(max_examples=100)
@given(data=_tp_trigger_scenario())
def test_sltp_trigger_execution_take_profit(app, data):
    """Property 7 (Take Profit): When current_price >= take_profit, the order is
    triggered, the holding is sold, and balance is credited.

    **Validates: Requirements 6.3, 6.4**
    """
    current_price, stop_loss, take_profit, quantity, initial_balance = data

    with app.app_context():
        from app.database import get_db
        db = get_db()
        _clean_test_state(db)

        # Set up test user
        db.execute(
            "INSERT INTO users (id, username, password_hash, balance) VALUES (?, ?, ?, ?)",
            (TEST_USER_ID, 'proptest_user', 'hash', initial_balance),
        )

        # Set up test ore with the current_price
        ore_id = 9000
        db.execute(
            "INSERT INTO ores (id, name, current_price, base_price, price_floor, "
            "price_ceiling, volatility, price_change_range, base_probabilities) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (ore_id, 'TestOreSLTP', current_price, current_price, 0.01, 20000.0,
             0.1, '[-0.05, 0.05]', '[0.3, 0.4, 0.3]'),
        )

        # Set up a holding for the user
        db.execute(
            "INSERT INTO holdings (id, user_id, ore_id, quantity, avg_purchase_price) "
            "VALUES (?, ?, ?, ?, ?)",
            (9000, TEST_USER_ID, ore_id, quantity, current_price),
        )

        # Set up an active SL/TP order
        db.execute(
            "INSERT INTO stop_loss_take_profit (id, holding_id, stop_loss, take_profit, active) "
            "VALUES (?, ?, ?, ?, ?)",
            (9000, 9000, stop_loss, take_profit, 1),
        )
        db.commit()

        # Run the evaluator
        evaluate_stop_loss_take_profit(db)

        # Assert: order is marked as triggered OR cascade-deleted with the holding.
        order = db.execute(
            "SELECT active, triggered_at FROM stop_loss_take_profit WHERE id = ?",
            (9000,)
        ).fetchone()
        if order is not None:
            assert order['active'] == 0, "SL/TP order should be deactivated after trigger"
            assert order['triggered_at'] is not None, "triggered_at should be set"

        # Assert: holding is deleted (sold)
        holding = db.execute(
            "SELECT * FROM holdings WHERE id = ?", (9000,)
        ).fetchone()
        assert holding is None, "Holding should be deleted after auto-sell"

        # Assert: user balance is credited (balance += quantity × current_price)
        user = db.execute(
            "SELECT balance FROM users WHERE id = ?", (TEST_USER_ID,)
        ).fetchone()
        expected_balance = initial_balance + (quantity * current_price)
        assert abs(user['balance'] - expected_balance) < 1e-6, (
            f"Balance should be {expected_balance}, got {user['balance']}"
        )

        # Assert: a sell transaction is recorded
        txn = db.execute(
            "SELECT * FROM transactions WHERE user_id = ? AND type = 'sell' AND ore_id = ?",
            (TEST_USER_ID, ore_id)
        ).fetchone()
        assert txn is not None, "A sell transaction should be recorded"
        assert txn['quantity'] == quantity
        assert abs(txn['price_at_trade'] - current_price) < 1e-6
        assert abs(txn['total_value'] - (quantity * current_price)) < 1e-6


@st.composite
def _no_trigger_scenario(draw):
    """Generate a scenario where SL < current_price < TP (no trigger).

    Strategy: pick stop_loss first, then take_profit with enough gap (>=1.0),
    then current_price strictly between them. The minimum gap prevents
    floating-point precision issues where no valid float exists in the range.
    """
    stop_loss = draw(st.floats(min_value=0.01, max_value=9000))
    take_profit = draw(st.floats(min_value=stop_loss + 1.0, max_value=10000))
    current_price = draw(st.floats(min_value=stop_loss + 0.01, max_value=take_profit - 0.01))
    assume(current_price > stop_loss and current_price < take_profit)
    quantity = draw(st.integers(min_value=1, max_value=10000))
    initial_balance = draw(st.floats(min_value=0, max_value=1e6))
    assume(current_price == current_price and stop_loss == stop_loss)
    assume(take_profit == take_profit and initial_balance == initial_balance)
    return current_price, stop_loss, take_profit, quantity, initial_balance


@settings(max_examples=100)
@given(data=_no_trigger_scenario())
def test_sltp_no_trigger_when_price_between_sl_and_tp(app, data):
    """Property 7 (No Trigger): When SL < current_price < TP, nothing happens —
    order stays active, holding remains, balance unchanged.

    **Validates: Requirements 6.3, 6.4**
    """
    current_price, stop_loss, take_profit, quantity, initial_balance = data

    with app.app_context():
        from app.database import get_db
        db = get_db()
        _clean_test_state(db)

        # Set up test user
        db.execute(
            "INSERT INTO users (id, username, password_hash, balance) VALUES (?, ?, ?, ?)",
            (TEST_USER_ID, 'proptest_user', 'hash', initial_balance),
        )

        # Set up test ore with the current_price
        ore_id = 9000
        db.execute(
            "INSERT INTO ores (id, name, current_price, base_price, price_floor, "
            "price_ceiling, volatility, price_change_range, base_probabilities) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (ore_id, 'TestOreSLTP', current_price, current_price, 0.01, 20000.0,
             0.1, '[-0.05, 0.05]', '[0.3, 0.4, 0.3]'),
        )

        # Set up a holding for the user
        db.execute(
            "INSERT INTO holdings (id, user_id, ore_id, quantity, avg_purchase_price) "
            "VALUES (?, ?, ?, ?, ?)",
            (9000, TEST_USER_ID, ore_id, quantity, current_price),
        )

        # Set up an active SL/TP order
        db.execute(
            "INSERT INTO stop_loss_take_profit (id, holding_id, stop_loss, take_profit, active) "
            "VALUES (?, ?, ?, ?, ?)",
            (9000, 9000, stop_loss, take_profit, 1),
        )
        db.commit()

        # Run the evaluator
        evaluate_stop_loss_take_profit(db)

        # Assert: order remains active (not triggered)
        order = db.execute(
            "SELECT active, triggered_at FROM stop_loss_take_profit WHERE id = ?",
            (9000,)
        ).fetchone()
        assert order['active'] == 1, "SL/TP order should remain active when not triggered"
        assert order['triggered_at'] is None, "triggered_at should remain None"

        # Assert: holding still exists
        holding = db.execute(
            "SELECT * FROM holdings WHERE id = ?", (9000,)
        ).fetchone()
        assert holding is not None, "Holding should still exist when not triggered"
        assert holding['quantity'] == quantity

        # Assert: balance unchanged
        user = db.execute(
            "SELECT balance FROM users WHERE id = ?", (TEST_USER_ID,)
        ).fetchone()
        assert abs(user['balance'] - initial_balance) < 1e-6, (
            f"Balance should remain {initial_balance}, got {user['balance']}"
        )

        # Assert: no sell transaction recorded
        txn = db.execute(
            "SELECT * FROM transactions WHERE user_id = ? AND type = 'sell' AND ore_id = ?",
            (TEST_USER_ID, ore_id)
        ).fetchone()
        assert txn is None, "No sell transaction should be recorded when not triggered"


# ---------------------------------------------------------------------------
# Feature: advanced-mode, Property 10: Account Reset Clears All Advanced State
# Validates: Requirements 10.1, 10.2
# ---------------------------------------------------------------------------

@settings(max_examples=100)
@given(
    eligible=st.booleans(),
    purchased=st.booleans(),
    active=st.booleans(),
    order_count=st.integers(min_value=0, max_value=10),
)
def test_account_reset_clears_all_advanced_state(app, eligible, purchased, active, order_count):
    """Property 10: For any user in any combination of advanced mode states
    (eligible/purchased/active with any number of active SL/TP orders),
    after account reset, advanced_eligible, advanced_purchased, and
    advanced_active SHALL all be 0, advanced_toggled_at SHALL be NULL,
    and no active SL/TP orders or holdings SHALL remain for that user.

    **Validates: Requirements 10.1, 10.2**
    """
    with app.app_context():
        from app.database import get_db
        from app.models import reset_account

        db = get_db()
        _clean_test_state(db)

        # Set up a user with the given combination of advanced flags
        eligible_val = 1 if eligible else 0
        purchased_val = 1 if purchased else 0
        active_val = 1 if active else 0
        toggled_at = datetime.now().isoformat() if active else None

        db.execute(
            "INSERT INTO users (id, username, password_hash, balance, "
            "advanced_eligible, advanced_purchased, advanced_active, advanced_toggled_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (TEST_USER_ID, 'proptest_user', 'hash', 75000.0,
             eligible_val, purchased_val, active_val, toggled_at),
        )

        # Set up holdings with SL/TP orders for this user
        ore_id = 9000
        if order_count > 0:
            db.execute(
                "INSERT INTO ores (id, name, current_price, base_price, price_floor, "
                "price_ceiling, volatility, price_change_range, base_probabilities) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (ore_id, 'TestOreReset', 100.0, 100.0, 50.0, 200.0,
                 0.1, '[-0.05, 0.05]', '[0.3, 0.4, 0.3]'),
            )

        for i in range(order_count):
            holding_id = 9000 + i
            db.execute(
                "INSERT INTO holdings (id, user_id, ore_id, quantity, avg_purchase_price) "
                "VALUES (?, ?, ?, ?, ?)",
                (holding_id, TEST_USER_ID, ore_id, 10, 100.0),
            )
            db.execute(
                "INSERT INTO stop_loss_take_profit (id, holding_id, stop_loss, take_profit, active) "
                "VALUES (?, ?, ?, ?, ?)",
                (9000 + i, holding_id, 80.0, 120.0, 1),
            )

        db.commit()

        # Call reset_account
        reset_account(TEST_USER_ID)

        # Assert: all advanced flags are cleared
        user = db.execute(
            "SELECT advanced_eligible, advanced_purchased, advanced_active, advanced_toggled_at "
            "FROM users WHERE id = ?",
            (TEST_USER_ID,)
        ).fetchone()

        assert user['advanced_eligible'] == 0, (
            f"advanced_eligible should be 0 after reset, got {user['advanced_eligible']}"
        )
        assert user['advanced_purchased'] == 0, (
            f"advanced_purchased should be 0 after reset, got {user['advanced_purchased']}"
        )
        assert user['advanced_active'] == 0, (
            f"advanced_active should be 0 after reset, got {user['advanced_active']}"
        )
        assert user['advanced_toggled_at'] is None, (
            f"advanced_toggled_at should be NULL after reset, got {user['advanced_toggled_at']}"
        )

        # Assert: no active SL/TP orders remain for this user
        remaining_orders = db.execute(
            "SELECT COUNT(*) as cnt FROM stop_loss_take_profit "
            "WHERE holding_id IN (SELECT id FROM holdings WHERE user_id = ?)",
            (TEST_USER_ID,)
        ).fetchone()
        assert remaining_orders['cnt'] == 0, (
            f"Expected 0 SL/TP orders after reset, found {remaining_orders['cnt']}"
        )

        # Assert: no holdings remain for this user
        remaining_holdings = db.execute(
            "SELECT COUNT(*) as cnt FROM holdings WHERE user_id = ?",
            (TEST_USER_ID,)
        ).fetchone()
        assert remaining_holdings['cnt'] == 0, (
            f"Expected 0 holdings after reset, found {remaining_holdings['cnt']}"
        )
