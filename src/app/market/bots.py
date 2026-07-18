"""Bot player logic.

Bots are real users in the database with balances, holdings, and transactions.
They appear on the leaderboard alongside real players.
Each tick, each bot makes one decision per ore: buy, hold, or sell.
Bots can also open and close short positions when market conditions are bearish.
"""

import json
import random
from datetime import datetime

from app.config import Config
from app.market.shorting import (
    _calculate_short_ratio,
    _calculate_collateral_multiplier,
    _calculate_total_locked_collateral,
    _calculate_player_margin,
    _calculate_tick_fee,
    _get_ticks_per_hour,
)

NUM_BOTS = 9
QUANTITY_MIN = 5
QUANTITY_MAX = 30

BOT_NAMES = [
    'SteveBot', 'AlexBot', 'CreeperTrader', 'EnderInvestor',
    'ZombieTrader', 'SkeletonMiner', 'WitchBroker', 'PiglinDealer', 'VillagerMerchant'
]


def ensure_bots_exist(db, default_balance):
    """Create bot user accounts if they don't already exist."""
    for name in BOT_NAMES:
        existing = db.execute("SELECT id FROM users WHERE username = ?", (name,)).fetchone()
        if not existing:
            now = datetime.now().isoformat()
            db.execute(
                "INSERT INTO users (username, password_hash, balance, created_at) VALUES (?, ?, ?, ?)",
                (name, 'BOT_NO_LOGIN', default_balance, now)
            )
    db.commit()


def get_bot_user_ids(db):
    """Get all bot user IDs."""
    rows = db.execute(
        "SELECT id FROM users WHERE username IN ({})".format(
            ','.join('?' * len(BOT_NAMES))
        ),
        BOT_NAMES
    ).fetchall()
    return [row['id'] for row in rows]


def execute_bot_trades(db, ores):
    """Execute bot trades for all ores. Bots act like real users with balance checks.

    Returns net buy/sell units per ore for influence calculation.
    """
    bot_ids = get_bot_user_ids(db)
    if not bot_ids:
        return {}

    # Track net influence per ore
    net_influence = {}  # {ore_id: net_buy_units}

    for ore in ores:
        ore_id = ore['id']
        current_price = ore['current_price']
        base_price = ore['base_price']
        net_units = 0

        for bot_id in bot_ids:
            # Check if bot should close any existing short positions (SL hit)
            short_close_units = _bot_check_short_closes(db, bot_id, ore_id, current_price)
            net_units += short_close_units  # Closing short = buy pressure

            # Evaluate whether bot should open a new short
            if _bot_short_decision(db, bot_id, ore):
                quantity = random.randint(QUANTITY_MIN, QUANTITY_MAX)
                opened = _bot_open_short(db, bot_id, ore_id, quantity, current_price)
                if opened:
                    net_units -= quantity  # Opening short = sell pressure
                    continue  # Skip normal buy/sell decision if shorted

            decision = _get_bot_decision(current_price, base_price)
            if decision == 'hold':
                continue

            quantity = random.randint(QUANTITY_MIN, QUANTITY_MAX)

            if decision == 'buy':
                _bot_buy(db, bot_id, ore_id, quantity, current_price)
                net_units += quantity
            elif decision == 'sell':
                actual_sold = _bot_sell(db, bot_id, ore_id, quantity, current_price)
                net_units -= actual_sold

        net_influence[ore_id] = net_units

    db.commit()
    return net_influence


def _get_bot_decision(current_price, base_price):
    """Determine a single bot's decision based on price vs base."""
    if current_price < base_price:
        weights = [50, 30, 20]  # buy, hold, sell
    elif current_price > base_price:
        weights = [20, 30, 50]  # buy, hold, sell
    else:
        weights = [33, 34, 33]  # buy, hold, sell

    return random.choices(['buy', 'hold', 'sell'], weights=weights, k=1)[0]


def _bot_buy(db, bot_id, ore_id, quantity, price):
    """Execute a bot buy if they have sufficient balance."""
    total_cost = quantity * price

    # Check balance
    user = db.execute("SELECT balance FROM users WHERE id = ?", (bot_id,)).fetchone()
    if not user or user['balance'] < total_cost:
        # Can't afford — buy fewer or skip
        if user and user['balance'] >= price:
            quantity = int(user['balance'] / price)
            total_cost = quantity * price
        else:
            return

    # Deduct balance
    db.execute("UPDATE users SET balance = balance - ? WHERE id = ?", (total_cost, bot_id))

    # Update or create holding
    holding = db.execute(
        "SELECT id, quantity, avg_purchase_price FROM holdings WHERE user_id = ? AND ore_id = ?",
        (bot_id, ore_id)
    ).fetchone()

    if holding:
        old_qty = holding['quantity']
        old_avg = holding['avg_purchase_price']
        new_qty = old_qty + quantity
        new_avg = ((old_qty * old_avg) + (quantity * price)) / new_qty
        db.execute(
            "UPDATE holdings SET quantity = ?, avg_purchase_price = ? WHERE id = ?",
            (new_qty, new_avg, holding['id'])
        )
    else:
        db.execute(
            "INSERT INTO holdings (user_id, ore_id, quantity, avg_purchase_price) VALUES (?, ?, ?, ?)",
            (bot_id, ore_id, quantity, price)
        )

    # Record transaction
    now = datetime.now().isoformat()
    db.execute(
        "INSERT INTO transactions (user_id, ore_id, type, quantity, price_at_trade, total_value, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (bot_id, ore_id, 'buy', quantity, price, total_cost, now)
    )


def _bot_sell(db, bot_id, ore_id, quantity, price):
    """Execute a bot sell if they hold enough. Returns actual quantity sold."""
    holding = db.execute(
        "SELECT id, quantity FROM holdings WHERE user_id = ? AND ore_id = ?",
        (bot_id, ore_id)
    ).fetchone()

    if not holding or holding['quantity'] == 0:
        return 0

    # Sell up to what they hold
    actual_qty = min(quantity, holding['quantity'])
    total_proceeds = actual_qty * price

    # Credit balance
    db.execute("UPDATE users SET balance = balance + ? WHERE id = ?", (total_proceeds, bot_id))

    # Update or delete holding
    new_qty = holding['quantity'] - actual_qty
    if new_qty == 0:
        db.execute("DELETE FROM holdings WHERE id = ?", (holding['id'],))
    else:
        db.execute("UPDATE holdings SET quantity = ? WHERE id = ?", (new_qty, holding['id']))

    # Record transaction
    now = datetime.now().isoformat()
    db.execute(
        "INSERT INTO transactions (user_id, ore_id, type, quantity, price_at_trade, total_value, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (bot_id, ore_id, 'sell', actual_qty, price, total_proceeds, now)
    )

    return actual_qty


def _bot_short_decision(db, bot_id: int, ore: dict) -> bool:
    """Evaluate whether a bot should open a short. Requires:
    - 4/5 recent trend_log entries are 'fall'
    - Bot FreeCash after collateral lockup can sustain >= 30 ticks of fees
    - Bot total short capital < 30% of total balance

    Args:
        db: An active sqlite3 connection.
        bot_id: The bot's user ID.
        ore: A dict-like row from the ores table (must include 'trend_log', 'current_price',
             'volatility', 'id').

    Returns:
        True if bot should short, False otherwise.
    """
    # Condition 1: Check trend_log — at least 4 out of 5 entries must be "fall"
    trend_log_raw = ore['trend_log']
    if isinstance(trend_log_raw, str):
        trend_log = json.loads(trend_log_raw)
    else:
        trend_log = list(trend_log_raw)

    fall_count = trend_log.count('fall')
    if fall_count < Config.BOT_SHORT_TREND_THRESHOLD:
        return False

    # Get bot's current balance (FreeCash)
    user_row = db.execute(
        "SELECT balance FROM users WHERE id = ?", (bot_id,)
    ).fetchone()
    if user_row is None:
        return False
    bot_balance = user_row['balance']

    # Condition 3: Total short capital < 30% of bot balance
    # Total short capital = sum of locked_collateral for all active bot shorts
    total_short_capital_row = db.execute(
        "SELECT COALESCE(SUM(locked_collateral), 0) as total FROM short_positions WHERE user_id = ? AND status = 'active'",
        (bot_id,)
    ).fetchone()
    total_short_capital = total_short_capital_row['total']

    # The cap is on total balance (FreeCash + existing short capital)
    total_bot_balance = bot_balance + total_short_capital
    if total_bot_balance <= 0:
        return False

    if total_short_capital >= Config.BOT_SHORT_CAPITAL_CAP * total_bot_balance:
        return False

    # Condition 2: FreeCash after collateral lockup can sustain >= 30 ticks of fees
    # Estimate collateral for a typical bot short (use midpoint quantity)
    quantity = (QUANTITY_MIN + QUANTITY_MAX) // 2
    current_price = ore['current_price']
    ore_id = ore['id']

    short_ratio = _calculate_short_ratio(db, ore_id)
    multiplier = _calculate_collateral_multiplier(short_ratio)
    estimated_margin = _calculate_player_margin(quantity, current_price, multiplier)

    # FreeCash remaining after paying margin
    remaining_freecash = bot_balance - estimated_margin
    if remaining_freecash <= 0:
        return False

    # Estimate tick fee for the potential position
    short_value = quantity * current_price
    volatility = ore['volatility'] if 'volatility' in ore.keys() else 0.5
    ticks_per_hour = _get_ticks_per_hour()
    tick_fee = _calculate_tick_fee(short_value, volatility, ticks_per_hour)

    # Check if remaining FreeCash can sustain at least 30 ticks of fees
    if tick_fee <= 0:
        return True  # No fee cost, can sustain indefinitely

    ticks_sustainable = remaining_freecash / tick_fee
    if ticks_sustainable < Config.BOT_SHORT_SUSTAIN_TICKS:
        return False

    return True


def _bot_open_short(db, bot_id: int, ore_id: int, quantity: int, price: float) -> bool:
    """Open a bot short position with mandatory SL at 5% above entry price.

    Args:
        db: An active sqlite3 connection.
        bot_id: The bot's user ID.
        ore_id: The ore to short.
        quantity: Number of shares to short.
        price: Current ore price (entry price).

    Returns:
        True if the short was successfully opened, False if rejected.
    """
    # Calculate collateral requirement (Shorting_fixup.md: vault vs margin)
    short_ratio = _calculate_short_ratio(db, ore_id)
    multiplier = _calculate_collateral_multiplier(short_ratio)
    locked_collateral = _calculate_total_locked_collateral(quantity, price, multiplier)
    player_margin = _calculate_player_margin(quantity, price, multiplier)

    # Check bot has enough FreeCash for MARGIN (not full vault)
    user_row = db.execute(
        "SELECT balance FROM users WHERE id = ?", (bot_id,)
    ).fetchone()
    if user_row is None:
        return False

    bot_balance = user_row['balance']
    if bot_balance < player_margin:
        # Try with a smaller quantity the bot can afford
        if bot_balance >= price * multiplier:
            quantity = int(bot_balance / (price * multiplier))
            if quantity < 1:
                return False
            locked_collateral = _calculate_total_locked_collateral(quantity, price, multiplier)
            player_margin = _calculate_player_margin(quantity, price, multiplier)
        else:
            return False

    # Capital cap check: ensure total short capital stays < 30% of total balance
    total_short_capital_row = db.execute(
        "SELECT COALESCE(SUM(locked_collateral), 0) as total FROM short_positions WHERE user_id = ? AND status = 'active'",
        (bot_id,)
    ).fetchone()
    total_short_capital = total_short_capital_row['total']
    total_bot_balance = bot_balance + total_short_capital

    if (total_short_capital + locked_collateral) >= Config.BOT_SHORT_CAPITAL_CAP * total_bot_balance:
        return False

    # Mandatory SL at entry_price × 1.05 (5% above entry)
    stop_loss_price = round(price * (1 + Config.BOT_SHORT_SL_PERCENT), 2)

    # Deduct MARGIN (not vault) from bot balance
    db.execute(
        "UPDATE users SET balance = balance - ? WHERE id = ?",
        (player_margin, bot_id)
    )

    # Create the short position (vault stores full locked_collateral)
    now = datetime.now().isoformat()
    db.execute(
        """INSERT INTO short_positions
           (user_id, ore_id, share_quantity, entry_price, locked_collateral,
            stop_loss_price, take_profit_price, cumulative_fees_paid, opened_at, status)
           VALUES (?, ?, ?, ?, ?, ?, NULL, 0.0, ?, 'active')""",
        (bot_id, ore_id, quantity, price, locked_collateral, stop_loss_price, now)
    )

    # Record transaction
    db.execute(
        """INSERT INTO transactions
           (user_id, ore_id, type, quantity, price_at_trade, total_value, created_at)
           VALUES (?, ?, 'short_open', ?, ?, ?, ?)""",
        (bot_id, ore_id, quantity, price, player_margin, now)
    )

    return True


def _bot_close_short(db, bot_id: int, position_id: int, price: float) -> int:
    """Close a bot short position (triggered by SL/TP or voluntary).

    Args:
        db: An active sqlite3 connection.
        bot_id: The bot's user ID.
        position_id: The short position ID to close.
        price: Current ore price at time of close.

    Returns:
        The share quantity of the closed position (for influence tracking),
        or 0 if the position was not found/not closeable.
    """
    # Fetch the position
    position = db.execute(
        "SELECT * FROM short_positions WHERE id = ? AND user_id = ? AND status = 'active'",
        (position_id, bot_id)
    ).fetchone()

    if position is None:
        return 0

    shares = position['share_quantity']
    locked_collateral = position['locked_collateral']

    # Calculate buyback cost (Short_Value)
    short_value = shares * price

    # P/L: positive means profit (price fell), negative means loss (price rose)
    pnl = locked_collateral - short_value

    # Credit/debit the bot's FreeCash
    db.execute(
        "UPDATE users SET balance = balance + ? WHERE id = ?",
        (round(pnl, 2), bot_id)
    )

    # Mark position as closed
    db.execute(
        "UPDATE short_positions SET status = 'closed', closed_at = datetime('now') WHERE id = ?",
        (position_id,)
    )

    # Record transaction
    now = datetime.now().isoformat()
    db.execute(
        """INSERT INTO transactions
           (user_id, ore_id, type, quantity, price_at_trade, total_value, created_at)
           VALUES (?, ?, 'short_close', ?, ?, ?, ?)""",
        (bot_id, position['ore_id'], shares, price, round(pnl, 2), now)
    )

    return shares


def _bot_check_short_closes(db, bot_id: int, ore_id: int, current_price: float) -> int:
    """Check if any bot short positions on this ore should be closed (SL hit).

    The main shorting engine's SL/TP evaluation (Phase 1) handles this during
    process_short_positions, but bots also proactively check here so that the
    influence from closing is registered in the same tick's bot influence queue.

    Args:
        db: An active sqlite3 connection.
        bot_id: The bot's user ID.
        ore_id: The ore being processed.
        current_price: The ore's current market price.

    Returns:
        Total shares closed (buy-side influence units).
    """
    # Fetch active bot short positions on this ore that have SL triggered
    positions = db.execute(
        """SELECT * FROM short_positions
           WHERE user_id = ? AND ore_id = ? AND status = 'active'
           AND stop_loss_price IS NOT NULL AND stop_loss_price <= ?""",
        (bot_id, ore_id, current_price)
    ).fetchall()

    total_closed_shares = 0
    for pos in positions:
        closed_qty = _bot_close_short(db, bot_id, pos['id'], current_price)
        total_closed_shares += closed_qty

    return total_closed_shares
