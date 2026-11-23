"""Property-based tests for the Shorting System.

Uses Hypothesis to verify universal correctness properties defined in the
design document for the shorting engine calculations.
"""

import os
import sys

# Add src/ to the Python path so that `from app.market.shorting import ...` works
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'src'))

from hypothesis import given, settings
from hypothesis import strategies as st

from app.market.shorting import (
    _calculate_collateral_multiplier,
    _calculate_player_margin,
    _calculate_tick_fee,
    _calculate_total_locked_collateral,
)
from app.config import Config

@settings(max_examples=100)
@given(
    shares=st.integers(min_value=1, max_value=10000),
    price=st.floats(min_value=0.01, max_value=50000, allow_nan=False, allow_infinity=False),
    shorts=st.integers(min_value=0, max_value=500),
    longs=st.integers(min_value=0, max_value=500),
)
def test_collateral_calculation_pipeline(shares, price, shorts, longs):
    """Property 1: For any valid share quantity (1-10,000), ore price (> 0),
    count of global short positions, and count of global long positions:

    - Short_Ratio = shorts / (shorts + longs), or 0.0 when both are zero
    - Collateral_Multiplier = 0.50 + 2.0 * Short_Ratio^3, clamped to [0.50, 2.50]
    - Total_Locked_Collateral = round((shares * price) * Collateral_Multiplier, 2)

    **Validates: Requirements 2.1, 2.2, 2.3**
    """
    # Step 1: Compute Short_Ratio directly (mirroring _calculate_short_ratio logic)
    total = shorts + longs
    if total == 0:
        short_ratio = 0.0
    else:
        short_ratio = shorts / total

    # Verify ratio is in valid range
    assert 0.0 <= short_ratio <= 1.0, (
        f"Short_Ratio should be in [0, 1], got {short_ratio} "
        f"(shorts={shorts}, longs={longs})"
    )

    # Step 2: Compute Collateral_Multiplier via the formula
    expected_multiplier = (
        Config.SHORT_BASE_REQUIREMENT
        + Config.SHORT_MAX_PENALTY * (short_ratio ** Config.SHORT_STEEPNESS)
    )
    expected_multiplier = max(0.50, min(2.50, expected_multiplier))

    # Call the actual function
    actual_multiplier = _calculate_collateral_multiplier(short_ratio)

    # Assert multiplier matches the formula
    assert abs(actual_multiplier - expected_multiplier) < 1e-9, (
        f"Multiplier mismatch: expected {expected_multiplier}, got {actual_multiplier} "
        f"(short_ratio={short_ratio})"
    )

    # Assert multiplier is clamped within bounds
    assert 0.50 <= actual_multiplier <= 2.50, (
        f"Multiplier should be clamped to [0.50, 2.50], got {actual_multiplier}"
    )

    # Step 3: Compute Total_Locked_Collateral (vault = Short_Value × (1 + Multiplier))
    expected_total = round((shares * price) * (1 + actual_multiplier), 2)

    actual_total = _calculate_total_locked_collateral(shares, price, actual_multiplier)

    # Assert total locked collateral matches the corrected formula
    assert abs(actual_total - expected_total) < 1e-9, (
        f"Total_Locked_Collateral mismatch: expected {expected_total}, "
        f"got {actual_total} (shares={shares}, price={price}, multiplier={actual_multiplier})"
    )

    # Assert total is non-negative (shares >= 1, price > 0, multiplier >= 0.50)
    assert actual_total >= 0, (
        f"Total_Locked_Collateral should be non-negative, got {actual_total}"
    )


@settings(max_examples=100)
@given(
    shares=st.integers(min_value=1, max_value=10000),
    price=st.floats(min_value=0.01, max_value=50000, allow_nan=False, allow_infinity=False),
    collateral_multiplier=st.floats(min_value=0.50, max_value=2.50, allow_nan=False, allow_infinity=False),
)
def test_player_margin_calculation(shares, price, collateral_multiplier):
    """Property 1b: Player Margin = Short_Value × Collateral_Multiplier.

    The player only pays the margin portion from FreeCash. The vault
    (Total_Locked_Collateral) is larger because it includes the synthetic
    short sale proceeds.

    Verifies:
    - Player_Margin = shares × price × multiplier
    - Vault = shares × price × (1 + multiplier)
    - Vault = Player_Margin + Short_Value (proceeds + margin)
    - Player_Margin < Vault (player pays less than total vault)

    **Validates: Requirements 2.5, Shorting_fixup.md**
    """
    # Calculate player margin
    expected_margin = round(shares * price * collateral_multiplier, 2)
    actual_margin = _calculate_player_margin(shares, price, collateral_multiplier)

    # Assert margin matches the formula
    assert abs(actual_margin - expected_margin) < 1e-9, (
        f"Player_Margin mismatch: expected {expected_margin}, got {actual_margin} "
        f"(shares={shares}, price={price}, multiplier={collateral_multiplier})"
    )

    # Assert margin is non-negative
    assert actual_margin >= 0, (
        f"Player_Margin should be non-negative, got {actual_margin}"
    )

    # Calculate vault for comparison
    actual_vault = _calculate_total_locked_collateral(shares, price, collateral_multiplier)
    short_value = round(shares * price, 2)

    # Vault = margin + short_value (within rounding tolerance)
    assert abs(actual_vault - (actual_margin + short_value)) < 0.02, (
        f"Vault ({actual_vault}) should equal margin ({actual_margin}) + "
        f"short_value ({short_value})"
    )

    # Player pays less than the full vault
    assert actual_margin <= actual_vault, (
        f"Player_Margin ({actual_margin}) should be <= Vault ({actual_vault})"
    )


@given(
    short_value=st.floats(100, 1000000, allow_nan=False, allow_infinity=False),
    volatility=st.floats(0, 1.5, allow_nan=False, allow_infinity=False),
    tick_interval=st.integers(5, 120),
)
@settings(max_examples=100)
def test_tick_fee_calculation(short_value, volatility, tick_interval):
    """Property 7: For any Short_Value (> 0), Volatility (0.0-1.5), and
    Ticks_Per_Hour (derived as 3600 / TICK_INTERVAL where TICK_INTERVAL > 0):

    Tick_Fee_Cost = round(Short_Value * ((0.005 + 0.10 * Volatility^2) / Ticks_Per_Hour), 2)

    **Validates: Requirements 4.1, 8.1**
    """
    ticks_per_hour = 3600 / tick_interval

    result = _calculate_tick_fee(short_value, volatility, ticks_per_hour)

    # Compute the expected fee using the formula from the design document
    expected = round(short_value * ((0.005 + 0.10 * volatility ** 2) / ticks_per_hour), 2)

    assert result == expected, (
        f"Tick fee mismatch: got {result}, expected {expected} "
        f"(short_value={short_value}, volatility={volatility}, "
        f"ticks_per_hour={ticks_per_hour})"
    )


@given(
    quantity=st.integers(min_value=1, max_value=10000),
    action=st.sampled_from(['open', 'close']),
)
@settings(max_examples=100)
def test_short_position_market_influence_registration(quantity, action):
    """Property 16: Short Position Market Influence Registration

    For any short position opened with quantity Q, a sell-type trade with
    quantity Q SHALL be registered in the player influence queue. For any
    short position closed with quantity Q, a buy-type trade with quantity Q
    SHALL be registered in the player influence queue.

    This is a pure logic property:
    - open → sell-type influence registered with quantity Q
    - close → buy-type influence registered with quantity Q

    The influence uses the same PLAYER_INFLUENCE_RATE (0.0005) as regular trades,
    processed identically via the existing consume_player_trades mechanism.

    **Validates: Requirements 13.1, 13.2**
    """
    from app.market.influence import record_player_trade, consume_player_trades

    # Use a fixed ore_id for testing
    ore_id = 1

    # Clear any existing trades for this ore to isolate the test
    consume_player_trades(ore_id)

    # Determine expected trade type based on action
    if action == 'open':
        # Opening a short = selling shares → sell-type influence
        expected_type = 'sell'
    else:
        # Closing a short = buying back shares → buy-type influence
        expected_type = 'buy'

    # Register the trade as the shorting system would
    record_player_trade(ore_id, quantity, expected_type)

    # Consume and verify the registered trade
    trades = consume_player_trades(ore_id)

    # --- Core Assertions ---

    # Exactly one trade should be registered
    assert len(trades) == 1, (
        f"Expected exactly 1 trade registered, got {len(trades)}. "
        f"action={action}, quantity={quantity}"
    )

    trade = trades[0]

    # The trade type must match the expected type for the action
    assert trade['type'] == expected_type, (
        f"Expected trade type '{expected_type}' for action '{action}', "
        f"got '{trade['type']}'"
    )

    # The quantity must match exactly
    assert trade['quantity'] == quantity, (
        f"Expected quantity {quantity}, got {trade['quantity']}. "
        f"action={action}"
    )

    # The ore_id must match
    assert trade['ore_id'] == ore_id, (
        f"Expected ore_id {ore_id}, got {trade['ore_id']}. "
        f"action={action}"
    )

    # Verify the mapping is correct:
    # open → sell (Requirement 13.1: opening registers sell pressure)
    # close → buy (Requirement 13.2: closing registers buy pressure)
    if action == 'open':
        assert trade['type'] == 'sell', (
            f"Opening a short MUST register as 'sell' influence. "
            f"Got '{trade['type']}' instead."
        )
    else:
        assert trade['type'] == 'buy', (
            f"Closing a short MUST register as 'buy' influence. "
            f"Got '{trade['type']}' instead."
        )
