"""Core market algorithm — processes one tick for all ores.

Each tick follows 8 steps per ore:
1. Calculate percentage-based price change amount
2. Apply trend effect to probabilities
3. Apply gravity effect to probabilities
4. Roll for market event (3x multiplier)
5. Apply player + bot influence to probabilities
6. Apply volatility scaling
7. Make market decision (rise/hold/fall)
8. Apply change, clamp to floor/ceiling, update trend log
"""

import json
import random
from datetime import datetime

from app.market.bots import execute_bot_trades, ensure_bots_exist
from app.market.events import roll_event, apply_event_multiplier
from app.market.influence import consume_player_trades

# Influence rate: 0.05% probability shift per unit traded
PLAYER_INFLUENCE_RATE = 0.0005
BOT_INFLUENCE_RATE = 0.0005

# Trend effect: 4% probability shift per matching entry in trend log
TREND_EFFECT_RATE = 4.0

# Gravity effect: 2% probability nudge per 10% drift from base
GRAVITY_RATE = 2.0
GRAVITY_DRIFT_STEP = 0.10  # 10%


def process_tick(db):
    """Process one market tick — update all ore prices.

    Args:
        db: An active sqlite3 connection (from the engine thread).
    """
    ores = db.execute("SELECT * FROM ores").fetchall()

    # Execute bot trades (real transactions in the database)
    bot_influence = execute_bot_trades(db, ores)

    for ore in ores:
        ore_id = ore['id']
        current_price = ore['current_price']
        base_price = ore['base_price']
        price_floor = ore['price_floor']
        price_ceiling = ore['price_ceiling']
        volatility = ore['volatility']
        trend_log = json.loads(ore['trend_log'])
        change_range = json.loads(ore['price_change_range'])
        base_probs = json.loads(ore['base_probabilities'])  # [rise, hold, fall]

        # --- Step 1: Calculate price change amount ---
        percentage = random.uniform(change_range[0], change_range[1]) / 100.0
        price_change = current_price * percentage

        # --- Step 2: Trend effect ---
        probs = list(base_probs)  # Copy: [rise, hold, fall]
        probs = _apply_trend_effect(probs, trend_log)

        # --- Step 3: Gravity effect ---
        probs = _apply_gravity_effect(probs, current_price, base_price)

        # --- Step 4: Event roll ---
        event_occurred = roll_event()
        if event_occurred:
            price_change = apply_event_multiplier(price_change)

        # --- Step 5: Player + bot influence ---
        probs = _apply_player_influence(probs, ore_id)
        probs = _apply_bot_influence_from_trades(probs, bot_influence.get(ore_id, 0))

        # --- Step 6: Volatility scaling ---
        price_change *= volatility
        probs = _apply_disruption(probs, volatility)

        # --- Step 7: Market decision ---
        decision = _weighted_random(probs)

        # --- Step 8: Apply and clamp ---
        if decision == 'rise':
            new_price = current_price + price_change
        elif decision == 'fall':
            new_price = current_price - price_change
        else:
            new_price = current_price

        # Clamp to floor/ceiling
        new_price = max(price_floor, min(price_ceiling, new_price))
        new_price = round(new_price, 2)

        # Update trend log (FIFO, keep last 5)
        trend_log.pop(0)
        trend_log.append(decision)

        # Persist changes
        now = datetime.now().isoformat()
        db.execute(
            "UPDATE ores SET current_price = ?, trend_log = ? WHERE id = ?",
            (new_price, json.dumps(trend_log), ore_id)
        )
        db.execute(
            "INSERT INTO price_history (ore_id, price, movement, created_at) VALUES (?, ?, ?, ?)",
            (ore_id, new_price, decision, now)
        )

    db.commit()


def _apply_trend_effect(probs, trend_log):
    """Adjust probabilities based on recent trend.

    If the trend has been rising, increase fall probability (mean reversion).
    If falling, increase rise probability.
    Each matching entry shifts by TREND_EFFECT_RATE%.
    """
    rise_count = trend_log.count('rise')
    fall_count = trend_log.count('fall')

    # Net trend: positive means rising trend, negative means falling
    net_trend = rise_count - fall_count

    if net_trend > 0:
        # Rising trend — nudge toward fall (mean reversion)
        shift = net_trend * TREND_EFFECT_RATE
        probs[0] -= shift  # reduce rise
        probs[2] += shift  # increase fall
    elif net_trend < 0:
        # Falling trend — nudge toward rise
        shift = abs(net_trend) * TREND_EFFECT_RATE
        probs[0] += shift  # increase rise
        probs[2] -= shift  # reduce fall

    return _normalise_probs(probs)


def _apply_gravity_effect(probs, current_price, base_price):
    """Pull price back toward base when it drifts too far.

    For every 10% drift from base, shift probability by GRAVITY_RATE%.
    """
    if base_price == 0:
        return probs

    drift = (current_price - base_price) / base_price
    drift_steps = abs(drift) / GRAVITY_DRIFT_STEP
    shift = drift_steps * GRAVITY_RATE

    if drift > 0:
        # Price above base — nudge toward fall
        probs[0] -= shift
        probs[2] += shift
    elif drift < 0:
        # Price below base — nudge toward rise
        probs[0] += shift
        probs[2] -= shift

    return _normalise_probs(probs)


def _apply_player_influence(probs, ore_id):
    """Apply player trade influence to probabilities."""
    trades = consume_player_trades(ore_id)
    if not trades:
        return probs

    net_buy_units = 0
    for trade in trades:
        if trade['type'] == 'buy':
            net_buy_units += trade['quantity']
        else:
            net_buy_units -= trade['quantity']

    shift = abs(net_buy_units) * PLAYER_INFLUENCE_RATE * 100  # Convert to percentage points

    if net_buy_units > 0:
        # Net buying pressure — nudge toward rise
        probs[0] += shift
        probs[2] -= shift
    elif net_buy_units < 0:
        # Net selling pressure — nudge toward fall
        probs[0] -= shift
        probs[2] += shift

    return _normalise_probs(probs)


def _apply_bot_influence_from_trades(probs, net_buy_units):
    """Apply bot trading influence to probabilities based on actual trades executed."""
    if net_buy_units == 0:
        return probs

    shift = abs(net_buy_units) * BOT_INFLUENCE_RATE * 100

    if net_buy_units > 0:
        probs[0] += shift
        probs[2] -= shift
    else:
        probs[0] -= shift
        probs[2] += shift

    return _normalise_probs(probs)


def _apply_disruption(probs, volatility):
    """High-volatility ores have a disruption bonus that reduces hold probability.

    This makes volatile ores move more often (less likely to hold).
    """
    # Disruption: reduce hold by (volatility * 10)%, split between rise and fall
    disruption = volatility * 10
    probs[1] -= disruption
    probs[0] += disruption / 2
    probs[2] += disruption / 2

    return _normalise_probs(probs)


def _weighted_random(probs):
    """Select rise, hold, or fall based on probability weights."""
    choices = ['rise', 'hold', 'fall']
    # Ensure all weights are positive
    safe_probs = [max(p, 1) for p in probs]
    return random.choices(choices, weights=safe_probs, k=1)[0]


def _normalise_probs(probs):
    """Ensure probabilities stay within reasonable bounds.

    Clamp each value to [1, 95] and ensure they sum to 100.
    """
    # Clamp individual values
    probs = [max(1.0, min(95.0, p)) for p in probs]

    # Normalise to sum to 100
    total = sum(probs)
    if total > 0:
        probs = [p * 100.0 / total for p in probs]

    return probs
