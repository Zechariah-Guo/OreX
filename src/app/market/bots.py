"""Bot player logic.

Bots are real users in the database with balances, holdings, and transactions.
They appear on the leaderboard alongside real players.
Each tick, each bot makes one decision per ore: buy, hold, or sell.
"""

import random
from datetime import datetime

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
