"""Resistance and support level calculator for Advanced Mode."""

from flask import current_app

from app.models import get_price_history


def calculate_levels(ore_id: int, lookback: int | None = None) -> dict:
    """Return {resistance: float, support: float} from recent price history.

    Queries the most recent `lookback` entries from price_history for the
    given ore and computes resistance (max price) and support (min price).

    Args:
        ore_id: The ore to calculate levels for.
        lookback: Number of recent price ticks to consider.
                  Defaults to Config.RS_LOOKBACK_WINDOW (50).

    Returns:
        Dict with 'resistance' and 'support' keys. Values are None if no
        price history exists for the ore.
    """
    if lookback is None:
        lookback = current_app.config['RS_LOOKBACK_WINDOW']

    history = get_price_history(ore_id, limit=lookback)
    prices = [row['price'] for row in history]

    if not prices:
        return {'resistance': None, 'support': None}

    return {
        'resistance': max(prices),
        'support': min(prices),
    }
