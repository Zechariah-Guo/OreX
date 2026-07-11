"""Thread-safe player influence tracking.

When a real user executes a trade, the system records it here.
On the next tick, the engine reads and consumes the buffer.
"""

import threading

_lock = threading.Lock()
_trades = []  # List of {'ore_id': int, 'quantity': int, 'type': 'buy'|'sell'}


def record_player_trade(ore_id, quantity, trade_type):
    """Record a player trade for influence on the next tick."""
    with _lock:
        _trades.append({
            'ore_id': ore_id,
            'quantity': quantity,
            'type': trade_type
        })


def consume_player_trades(ore_id):
    """Consume and return all player trades for a given ore since last tick."""
    with _lock:
        relevant = [t for t in _trades if t['ore_id'] == ore_id]
        _trades[:] = [t for t in _trades if t['ore_id'] != ore_id]
    return relevant
