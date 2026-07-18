"""Financial data access and calculation functions for the Finances Page.

Provides all read queries and derived calculations for the finances dashboard:
capital breakdown, active short position metrics, fee burn projections,
and cash runway indicators.
"""

import sys
import math

from app.config import Config
from app.database import get_db
from app.models import get_user_by_id, get_portfolio_value


def get_finances_data(user_id: int) -> dict:
    """Compute all financial data for the finances page.

    Returns dict with keys: free_cash, locked_collateral, total_short_equity,
    long_holdings_value, net_worth, short_positions, fee_burn_per_tick,
    fee_burn_per_hour, cash_runway_ticks, cash_runway_formatted,
    runway_color, runway_bar_width, total_exposure, total_fees_paid,
    position_count, ticks_per_hour, has_shorts.
    """
    ticks_per_hour = 3600 / Config.TICK_INTERVAL

    # Fetch user balance (free cash)
    user = get_user_by_id(user_id)
    free_cash = user.balance if user else 0.0

    # Fetch long holdings value
    long_holdings_value = get_portfolio_value(user_id)

    # Fetch active short positions with computed metrics
    positions = get_active_short_positions(user_id, free_cash, ticks_per_hour)
    has_shorts = len(positions) > 0

    # Compute aggregates
    if has_shorts:
        total_locked_collateral = sum(p['locked_collateral'] for p in positions)
        total_short_equity = sum(
            p['locked_collateral'] - p['short_value'] for p in positions
        )
        total_exposure = sum(p['short_value'] for p in positions)
        total_fees_paid = sum(p['cumulative_fees_paid'] for p in positions)
        fee_burn_per_tick = calculate_fee_burn_per_tick(positions, ticks_per_hour)
        fee_burn_per_hour = fee_burn_per_tick * ticks_per_hour
    else:
        total_locked_collateral = 0.0
        total_short_equity = 0.0
        total_exposure = 0.0
        total_fees_paid = 0.0
        fee_burn_per_tick = 0.0
        fee_burn_per_hour = 0.0

    # Cash runway
    cash_runway_ticks = calculate_cash_runway(free_cash, fee_burn_per_tick)
    cash_runway_formatted = format_runway_duration(cash_runway_ticks, Config.TICK_INTERVAL)
    runway_color = get_runway_color(cash_runway_ticks)
    runway_bar_width = get_runway_bar_width(cash_runway_ticks)

    # Net worth
    net_worth = free_cash + long_holdings_value + total_short_equity

    return {
        'free_cash': free_cash,
        'locked_collateral': total_locked_collateral,
        'total_short_equity': total_short_equity,
        'long_holdings_value': long_holdings_value,
        'net_worth': net_worth,
        'short_positions': positions,
        'fee_burn_per_tick': fee_burn_per_tick,
        'fee_burn_per_hour': fee_burn_per_hour,
        'cash_runway_ticks': cash_runway_ticks,
        'cash_runway_formatted': cash_runway_formatted,
        'runway_color': runway_color,
        'runway_bar_width': runway_bar_width,
        'total_exposure': total_exposure,
        'total_fees_paid': total_fees_paid,
        'position_count': len(positions),
        'ticks_per_hour': ticks_per_hour,
        'has_shorts': has_shorts,
    }


def get_active_short_positions(user_id: int, free_cash: float = 0.0, ticks_per_hour: float = None) -> list:
    """Fetch active short positions with computed per-position metrics.

    Each dict includes: id, ore_name, share_quantity, entry_price,
    short_value, locked_collateral, unrealized_pnl, stop_loss_price,
    take_profit_price, tick_fee, ticks_to_liquidation, cumulative_fees_paid,
    volatility, current_price, opened_at.
    """
    if ticks_per_hour is None:
        ticks_per_hour = 3600 / Config.TICK_INTERVAL

    db = get_db()
    rows = db.execute(
        """SELECT sp.id, sp.share_quantity, sp.entry_price, sp.locked_collateral,
                  sp.stop_loss_price, sp.take_profit_price, sp.cumulative_fees_paid,
                  sp.opened_at,
                  o.name AS ore_name, o.current_price, o.volatility
           FROM short_positions sp
           JOIN ores o ON sp.ore_id = o.id
           WHERE sp.user_id = ? AND sp.status = 'active'
           ORDER BY sp.opened_at ASC""",
        (user_id,)
    ).fetchall()

    positions = []
    for row in rows:
        share_quantity = row['share_quantity']
        entry_price = row['entry_price']
        current_price = row['current_price']
        volatility = row['volatility']
        locked_collateral = row['locked_collateral']

        short_value = share_quantity * current_price
        unrealized_pnl = (entry_price * share_quantity) - short_value
        tick_fee = round(
            short_value * ((0.005 + 0.10 * volatility ** 2) / ticks_per_hour), 2
        )

        if tick_fee > 0:
            ticks_to_liquidation = math.floor(free_cash / tick_fee)
        else:
            ticks_to_liquidation = sys.maxsize

        positions.append({
            'id': row['id'],
            'ore_name': row['ore_name'],
            'share_quantity': share_quantity,
            'entry_price': entry_price,
            'current_price': current_price,
            'short_value': short_value,
            'locked_collateral': locked_collateral,
            'unrealized_pnl': unrealized_pnl,
            'stop_loss_price': row['stop_loss_price'],
            'take_profit_price': row['take_profit_price'],
            'tick_fee': tick_fee,
            'ticks_to_liquidation': ticks_to_liquidation,
            'cumulative_fees_paid': row['cumulative_fees_paid'],
            'volatility': volatility,
            'opened_at': row['opened_at'],
        })

    return positions


def calculate_fee_burn_per_tick(positions: list, ticks_per_hour: float) -> float:
    """Sum of per-position tick fees using the shorting engine formula.

    Tick_Fee = round(Short_Value * ((0.005 + 0.10 * volatility^2) / ticks_per_hour), 2)

    Args:
        positions: List of position dicts with 'short_value' and 'volatility' keys.
        ticks_per_hour: Number of ticks per hour (3600 / tick_interval).

    Returns:
        Total fee burn per tick across all positions.
    """
    total = 0.0
    for pos in positions:
        short_value = pos['short_value']
        volatility = pos['volatility']
        tick_fee = round(
            short_value * ((0.005 + 0.10 * volatility ** 2) / ticks_per_hour), 2
        )
        total += tick_fee
    return total


def calculate_cash_runway(free_cash: float, fee_burn_per_tick: float) -> int:
    """Return integer tick count until free cash is exhausted.

    Returns sys.maxsize (effectively infinite) when fee_burn_per_tick is zero.
    """
    if fee_burn_per_tick <= 0:
        return sys.maxsize
    return math.floor(free_cash / fee_burn_per_tick)


def format_runway_duration(ticks: int, tick_interval: int) -> str:
    """Convert tick count to human-readable duration string.

    Examples: '~450 ticks / ~2h 30m', '~15 ticks / ~5m', '∞'
    """
    if ticks >= sys.maxsize:
        return "∞"

    total_seconds = ticks * tick_interval
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60

    if hours > 0 and minutes > 0:
        duration = f"~{hours}h {minutes}m"
    elif hours > 0:
        duration = f"~{hours}h"
    else:
        duration = f"~{minutes}m"

    return f"~{ticks} ticks / {duration}"


def get_runway_color(ticks: int) -> str:
    """Return 'green', 'amber', or 'red' based on runway thresholds.

    green: > 60 ticks (or infinite)
    amber: 20-60 ticks (inclusive)
    red: < 20 ticks
    """
    if ticks > 60:
        return 'green'
    elif ticks >= 20:
        return 'amber'
    else:
        return 'red'


def get_runway_bar_width(ticks: int) -> float:
    """Calculate bar width percentage for the runway indicator.

    Returns min(ticks / 120, 1.0) * 100, capped at 100%.
    When ticks is infinite (sys.maxsize), returns 100.0.
    """
    if ticks >= sys.maxsize:
        return 100.0
    return min(ticks / 120, 1.0) * 100


def format_currency(value: float) -> str:
    """Format a numeric value as currency: $X,XXX.XX.

    Args:
        value: Non-negative float to format.

    Returns:
        Formatted string like "$1,234.56".
    """
    return f"${value:,.2f}"


def format_percentage(value: float) -> str:
    """Format a numeric value as a percentage: X.X%.

    Args:
        value: Float value to format.

    Returns:
        Formatted string like "12.5%".
    """
    return f"{value:.1f}%"
