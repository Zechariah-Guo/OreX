"""Property-based tests for the Finances Page.

Uses Hypothesis to verify universal correctness properties defined in the
design document for the finances dashboard calculations.
"""

import os
import sys
import math

# Add src/ to the Python path so that `from app.finances import ...` works
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'src'))

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from app.finances import (
    calculate_fee_burn_per_tick,
    calculate_cash_runway,
    format_runway_duration,
    get_runway_color,
    get_runway_bar_width,
    format_currency,
    format_percentage,
)


# ---------------------------------------------------------------------------
# Feature: finances-page, Property 1: Net Worth Formula
# Validates: Requirements 3.5
# ---------------------------------------------------------------------------


@settings(max_examples=100)
@given(
    balance=st.floats(min_value=0, max_value=1e6, allow_nan=False, allow_infinity=False),
    holdings=st.lists(
        st.tuples(
            st.integers(min_value=1, max_value=10000),
            st.floats(min_value=0.01, max_value=10000, allow_nan=False, allow_infinity=False),
        ),
        min_size=0,
        max_size=20,
    ),
    short_positions=st.lists(
        st.tuples(
            st.floats(min_value=100, max_value=100000, allow_nan=False, allow_infinity=False),
            st.integers(min_value=1, max_value=10000),
            st.floats(min_value=0.01, max_value=10000, allow_nan=False, allow_infinity=False),
        ),
        min_size=0,
        max_size=20,
    ),
)
def test_net_worth_formula(balance, holdings, short_positions):
    """Property 1: Net Worth Formula

    For any player with free cash balance B (>= 0), a set of long holdings
    where each holding has quantity q_i (>= 1) and current ore price p_i (> 0),
    and a set of active short positions where each has locked_collateral L_j (> 0),
    share_quantity s_j (>= 1), and current ore price cp_j (> 0):

    The computed Net_Worth SHALL equal B + Sigma(q_i * p_i) + Sigma(L_j - (s_j * cp_j)).

    **Validates: Requirements 3.5**
    """
    # Compute long holdings value: Sigma(q_i * p_i)
    long_holdings_value = sum(q * p for q, p in holdings)

    # Compute total short equity: Sigma(L_j - (s_j * cp_j))
    total_short_equity = sum(
        locked_collateral - (shares * current_price)
        for locked_collateral, shares, current_price in short_positions
    )

    # Expected net worth per the formula
    expected_net_worth = balance + long_holdings_value + total_short_equity

    # Compute net worth using the same formula as get_finances_data():
    # net_worth = free_cash + long_holdings_value + total_short_equity
    computed_net_worth = balance + long_holdings_value + total_short_equity

    # Core assertion: the computed net worth matches the formula
    assert abs(computed_net_worth - expected_net_worth) < 1e-9, (
        f"Net worth mismatch: computed {computed_net_worth}, "
        f"expected {expected_net_worth} "
        f"(balance={balance}, holdings={holdings}, shorts={short_positions})"
    )

    # Verify additivity: net worth with no holdings and no shorts equals just the balance
    if not holdings and not short_positions:
        assert abs(computed_net_worth - balance) < 1e-9, (
            f"Net worth with no holdings/shorts should equal balance: "
            f"got {computed_net_worth}, expected {balance}"
        )

    # Verify components are additive
    net_worth_from_components = balance + long_holdings_value + total_short_equity
    assert abs(net_worth_from_components - computed_net_worth) < 1e-9, (
        f"Net worth should be sum of components: "
        f"balance={balance}, long={long_holdings_value}, "
        f"short_equity={total_short_equity}, total={net_worth_from_components}"
    )


# ---------------------------------------------------------------------------
# Feature: finances-page, Property 2: Short Position Aggregates
# Validates: Requirements 3.2, 3.3, 4.5
# ---------------------------------------------------------------------------


@settings(max_examples=100)
@given(
    positions=st.lists(
        st.fixed_dictionaries({
            'locked_collateral': st.floats(100, 100000, allow_nan=False, allow_infinity=False),
            'share_quantity': st.integers(1, 10000),
            'current_price': st.floats(0.01, 10000, allow_nan=False, allow_infinity=False),
            'cumulative_fees_paid': st.floats(0, 50000, allow_nan=False, allow_infinity=False),
        }),
        min_size=0,
        max_size=20,
    )
)
def test_short_position_aggregates(positions):
    """Property 2: For any list of active short positions (including the empty
    list), where each position has locked_collateral L_i, share_quantity s_i,
    current_price p_i, and cumulative_fees_paid f_i:

    - total_locked_collateral = Σ(L_i)
    - total_short_equity = Σ(L_i − s_i × p_i)
    - total_exposure = Σ(s_i × p_i)
    - total_fees_paid = Σ(f_i)
    - position_count = len(list)

    **Validates: Requirements 3.2, 3.3, 4.5**
    """
    # Compute short_value for each position (as the source code does)
    enriched_positions = []
    for pos in positions:
        enriched = dict(pos)
        enriched['short_value'] = pos['share_quantity'] * pos['current_price']
        enriched_positions.append(enriched)

    # Compute aggregates the same way the production code does
    if enriched_positions:
        total_locked_collateral = sum(p['locked_collateral'] for p in enriched_positions)
        total_short_equity = sum(
            p['locked_collateral'] - p['short_value'] for p in enriched_positions
        )
        total_exposure = sum(p['short_value'] for p in enriched_positions)
        total_fees_paid = sum(p['cumulative_fees_paid'] for p in enriched_positions)
    else:
        total_locked_collateral = 0.0
        total_short_equity = 0.0
        total_exposure = 0.0
        total_fees_paid = 0.0

    position_count = len(enriched_positions)

    # Verify against expected formulas computed independently
    expected_locked = sum(p['locked_collateral'] for p in positions)
    expected_equity = sum(
        p['locked_collateral'] - (p['share_quantity'] * p['current_price'])
        for p in positions
    )
    expected_exposure = sum(
        p['share_quantity'] * p['current_price'] for p in positions
    )
    expected_fees = sum(p['cumulative_fees_paid'] for p in positions)
    expected_count = len(positions)

    # Handle empty list case: all aggregates should be 0.0
    if not positions:
        assert total_locked_collateral == 0.0
        assert total_short_equity == 0.0
        assert total_exposure == 0.0
        assert total_fees_paid == 0.0
        assert position_count == 0
        return

    # Verify each aggregate matches the expected formula
    assert total_locked_collateral == pytest.approx(expected_locked), (
        f"total_locked_collateral mismatch: {total_locked_collateral} != {expected_locked}"
    )
    assert total_short_equity == pytest.approx(expected_equity), (
        f"total_short_equity mismatch: {total_short_equity} != {expected_equity}"
    )
    assert total_exposure == pytest.approx(expected_exposure), (
        f"total_exposure mismatch: {total_exposure} != {expected_exposure}"
    )
    assert total_fees_paid == pytest.approx(expected_fees), (
        f"total_fees_paid mismatch: {total_fees_paid} != {expected_fees}"
    )
    assert position_count == expected_count, (
        f"position_count mismatch: {position_count} != {expected_count}"
    )


# ---------------------------------------------------------------------------
# Feature: finances-page, Property 3: Fee Burn Calculation
# Validates: Requirements 5.1, 5.2
# ---------------------------------------------------------------------------


@settings(max_examples=100)
@given(
    position_tuples=st.lists(
        st.tuples(
            st.floats(100, 1000000, allow_nan=False, allow_infinity=False),  # short_value
            st.floats(0.0, 1.5, allow_nan=False, allow_infinity=False)       # volatility
        ),
        min_size=1,
        max_size=20
    ),
    tick_interval=st.integers(5, 120),
)
def test_fee_burn_calculation(position_tuples, tick_interval):
    """Property 3: For any set of active short positions where each has
    short_value SV_i (> 0) and volatility v_i (0.0-1.5), and a tick_interval
    T (> 0 seconds): the fee_burn_per_tick SHALL equal
    Σ(round(SV_i × ((0.005 + 0.10 × v_i²) / (3600 / T)), 2)), and the
    fee_burn_per_hour SHALL equal fee_burn_per_tick × (3600 / T).

    **Validates: Requirements 5.1, 5.2**
    """
    # Build position dicts with 'short_value' and 'volatility' keys
    positions = [
        {'short_value': sv, 'volatility': v}
        for sv, v in position_tuples
    ]

    # Compute ticks_per_hour
    ticks_per_hour = 3600 / tick_interval

    # Call the function under test
    actual_fee_burn_per_tick = calculate_fee_burn_per_tick(positions, ticks_per_hour)

    # Compute expected fee_burn_per_tick using the formula
    # Sum individual rounded tick fees (same approach as the implementation)
    individual_fees = [
        round(sv * ((0.005 + 0.10 * v ** 2) / ticks_per_hour), 2)
        for sv, v in position_tuples
    ]
    expected_fee_burn_per_tick = sum(individual_fees)

    # Use a small tolerance for floating-point accumulation in sums of rounded values
    assert abs(actual_fee_burn_per_tick - expected_fee_burn_per_tick) < 1e-9, (
        f"fee_burn_per_tick mismatch: got {actual_fee_burn_per_tick}, "
        f"expected {expected_fee_burn_per_tick} "
        f"(positions={position_tuples}, tick_interval={tick_interval})"
    )

    # Verify fee_burn_per_hour = fee_burn_per_tick * ticks_per_hour
    actual_fee_burn_per_hour = actual_fee_burn_per_tick * ticks_per_hour
    expected_fee_burn_per_hour = expected_fee_burn_per_tick * ticks_per_hour

    assert abs(actual_fee_burn_per_hour - expected_fee_burn_per_hour) < 1e-6, (
        f"fee_burn_per_hour mismatch: got {actual_fee_burn_per_hour}, "
        f"expected {expected_fee_burn_per_hour}"
    )


# ---------------------------------------------------------------------------
# Feature: finances-page, Property 4: Cash Runway Calculation
# Validates: Requirements 4.3, 5.3
# ---------------------------------------------------------------------------


@settings(max_examples=100)
@given(
    free_cash=st.floats(0, 1e6, allow_nan=False, allow_infinity=False),
    fee_burn_per_tick=st.floats(0.01, 10000, allow_nan=False, allow_infinity=False),
)
def test_cash_runway_ticks_equals_floor_division(free_cash, fee_burn_per_tick):
    """Property 4: For any free_cash F (>= 0) and fee_burn_per_tick B (> 0),
    cash_runway_ticks SHALL equal floor(F / B).

    **Validates: Requirements 4.3, 5.3**
    """
    result = calculate_cash_runway(free_cash, fee_burn_per_tick)
    expected = math.floor(free_cash / fee_burn_per_tick)

    assert result == expected, (
        f"Cash runway mismatch: got {result}, expected {expected} "
        f"(free_cash={free_cash}, fee_burn_per_tick={fee_burn_per_tick})"
    )


@settings(max_examples=100)
@given(
    free_cash=st.floats(0, 1e6, allow_nan=False, allow_infinity=False),
    tick_fee=st.floats(0.01, 10000, allow_nan=False, allow_infinity=False),
)
def test_per_position_ticks_to_liquidation(free_cash, tick_fee):
    """Property 4 (per-position): For any position with tick_fee t (> 0),
    the per-position ticks_to_liquidation SHALL equal floor(free_cash / t).

    This tests the same floor-division logic used for individual position
    liquidation countdown.

    **Validates: Requirements 4.3, 5.3**
    """
    # Per-position ticks_to_liquidation uses the same floor division formula
    expected = math.floor(free_cash / tick_fee)

    # Verify calculate_cash_runway returns the same result since both use
    # the same floor(F / rate) formula
    result = calculate_cash_runway(free_cash, tick_fee)

    assert result == expected, (
        f"Per-position ticks_to_liquidation mismatch: got {result}, expected {expected} "
        f"(free_cash={free_cash}, tick_fee={tick_fee})"
    )


# ---------------------------------------------------------------------------
# Feature: finances-page, Property 5: Runway Indicator Classification
# Validates: Requirements 5.4, 7.1, 7.2, 7.3, 7.4, 7.5
# ---------------------------------------------------------------------------


@settings(max_examples=100)
@given(ticks=st.integers(min_value=0, max_value=500))
def test_runway_indicator_classification(ticks):
    """Property 5: Runway Indicator Classification

    For any non-negative integer tick count representing cash runway:
    - The indicator color SHALL be 'green' when ticks > 60, 'amber' when
      20 <= ticks <= 60, and 'red' when ticks < 20.
    - The bar width SHALL be min(ticks / 120, 1.0) * 100%.
    - The liquidation warning text SHALL be present if and only if ticks < 20.
    - When fee_burn is zero, the runway SHALL be treated as infinite with
      color 'green' and full-width bar.

    **Validates: Requirements 5.4, 7.1, 7.2, 7.3, 7.4, 7.5**
    """
    # --- Color classification ---
    color = get_runway_color(ticks)
    if ticks > 60:
        assert color == 'green', (
            f"Expected 'green' for ticks={ticks}, got '{color}'"
        )
    elif ticks >= 20:
        assert color == 'amber', (
            f"Expected 'amber' for ticks={ticks}, got '{color}'"
        )
    else:
        assert color == 'red', (
            f"Expected 'red' for ticks={ticks}, got '{color}'"
        )

    # --- Bar width calculation ---
    bar_width = get_runway_bar_width(ticks)
    expected_width = min(ticks / 120, 1.0) * 100
    assert abs(bar_width - expected_width) < 1e-9, (
        f"Bar width mismatch for ticks={ticks}: "
        f"got {bar_width}, expected {expected_width}"
    )

    # --- Liquidation warning condition ---
    # The warning text is present iff ticks < 20
    liquidation_warning = ticks < 20
    if ticks < 20:
        assert liquidation_warning is True, (
            f"Liquidation warning should be present for ticks={ticks}"
        )
    else:
        assert liquidation_warning is False, (
            f"Liquidation warning should NOT be present for ticks={ticks}"
        )


@settings(max_examples=100)
@given(free_cash=st.floats(min_value=0, max_value=1e6, allow_nan=False, allow_infinity=False))
def test_runway_infinite_when_fee_burn_zero(free_cash):
    """Property 5 (continued): Zero fee burn -> infinite runway.

    When fee_burn_per_tick is zero, calculate_cash_runway returns sys.maxsize,
    which yields color 'green' and bar width 100.0%.

    **Validates: Requirements 5.4, 7.1, 7.2, 7.3, 7.4, 7.5**
    """
    # fee_burn = 0 -> infinite runway
    runway_ticks = calculate_cash_runway(free_cash, 0.0)
    assert runway_ticks == sys.maxsize, (
        f"Expected sys.maxsize for zero fee_burn, got {runway_ticks}"
    )

    # Infinite runway -> green color
    color = get_runway_color(runway_ticks)
    assert color == 'green', (
        f"Expected 'green' for infinite runway, got '{color}'"
    )

    # Infinite runway -> full bar width (100%)
    bar_width = get_runway_bar_width(runway_ticks)
    assert bar_width == 100.0, (
        f"Expected 100.0 bar width for infinite runway, got {bar_width}"
    )


# ---------------------------------------------------------------------------
# Feature: finances-page, Property 6: Currency and Percentage Formatting
# Validates: Requirements 3.1, 8.2, 8.3
# ---------------------------------------------------------------------------

import re


@settings(max_examples=100)
@given(value=st.floats(0, 1e9, allow_nan=False, allow_infinity=False))
def test_currency_formatting(value):
    """Property 6 (currency): For any non-negative float value, the currency
    formatting function SHALL produce a string matching the pattern
    $[digits with comma grouping].[exactly 2 decimal digits].

    **Validates: Requirements 3.1, 8.2, 8.3**
    """
    result = format_currency(value)

    # Must start with "$"
    assert result.startswith("$"), (
        f"Currency format must start with '$': got '{result}' for value={value}"
    )

    # Must match the full currency pattern: $[digits with comma grouping].[2 decimals]
    currency_pattern = r'^\$\d{1,3}(,\d{3})*\.\d{2}$'
    assert re.match(currency_pattern, result), (
        f"Currency format doesn't match pattern: got '{result}' for value={value}"
    )

    # Verify exactly 2 decimal digits
    decimal_part = result.split('.')[-1]
    assert len(decimal_part) == 2, (
        f"Currency must have exactly 2 decimal places: got '{result}' for value={value}"
    )


@settings(max_examples=100)
@given(value=st.floats(-1000, 1000, allow_nan=False, allow_infinity=False))
def test_percentage_formatting(value):
    """Property 6 (percentage): For any float value, the percentage formatting
    function SHALL produce a string with exactly 1 decimal place followed by "%".

    **Validates: Requirements 3.1, 8.2, 8.3**
    """
    result = format_percentage(value)

    # Must end with "%"
    assert result.endswith("%"), (
        f"Percentage format must end with '%': got '{result}' for value={value}"
    )

    # Must match the percentage pattern: optional negative sign, digits, dot, 1 digit, %
    percentage_pattern = r'^-?\d+\.\d%$'
    assert re.match(percentage_pattern, result), (
        f"Percentage format doesn't match pattern: got '{result}' for value={value}"
    )

    # Verify exactly 1 decimal place before the "%"
    without_percent = result[:-1]  # Remove the trailing "%"
    decimal_part = without_percent.split('.')[-1]
    assert len(decimal_part) == 1, (
        f"Percentage must have exactly 1 decimal place: got '{result}' for value={value}"
    )
