"""Data access functions for OreX.

All database queries live here. Functions accept and return
sqlite3.Row objects or dictionaries.
"""

from datetime import datetime

from flask import current_app
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash

from app.database import get_db


# --- User Model ---

class User(UserMixin):
    """User class for Flask-Login integration."""

    def __init__(self, id, username, balance):
        self.id = id
        self.username = username
        self.balance = balance


def create_user(username, password):
    """Create a new user with hashed password and default balance. Returns the new user's ID."""
    db = get_db()
    password_hash = generate_password_hash(password)
    default_balance = current_app.config['DEFAULT_BALANCE']
    now = datetime.now().isoformat()

    cursor = db.execute(
        "INSERT INTO users (username, password_hash, balance, created_at) VALUES (?, ?, ?, ?)",
        (username, password_hash, default_balance, now)
    )
    db.commit()
    return cursor.lastrowid


def get_user_by_id(user_id):
    """Fetch a user by ID. Returns a User object or None."""
    db = get_db()
    row = db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    if row:
        return User(row['id'], row['username'], row['balance'])
    return None


def get_user_by_username(username):
    """Fetch a user row by username. Returns sqlite3.Row or None."""
    db = get_db()
    return db.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()





def update_balance(user_id, new_balance):
    """Update a user's balance."""
    db = get_db()
    db.execute("UPDATE users SET balance = ? WHERE id = ?", (new_balance, user_id))
    db.commit()


def update_last_login(user_id):
    """Update the last_login timestamp for a user."""
    db = get_db()
    now = datetime.now().isoformat()
    db.execute("UPDATE users SET last_login = ? WHERE id = ?", (now, user_id))
    db.commit()


def verify_password(stored_hash, password):
    """Check a password against a stored hash."""
    return check_password_hash(stored_hash, password)


# --- Ore Model ---

def get_all_ores():
    """Fetch all ores. Returns a list of sqlite3.Row objects."""
    db = get_db()
    return db.execute("SELECT * FROM ores ORDER BY id").fetchall()


def get_ore_by_id(ore_id):
    """Fetch a single ore by ID. Returns sqlite3.Row or None."""
    db = get_db()
    return db.execute("SELECT * FROM ores WHERE id = ?", (ore_id,)).fetchone()


# --- Holdings Model ---

def get_holdings_by_user(user_id):
    """Fetch all holdings for a user, joined with ore data."""
    db = get_db()
    return db.execute(
        """SELECT h.id, h.user_id, h.ore_id, h.quantity, h.avg_purchase_price,
                  o.name, o.icon_filename, o.current_price, o.trend_log
           FROM holdings h
           JOIN ores o ON h.ore_id = o.id
           WHERE h.user_id = ?
           ORDER BY o.name""",
        (user_id,)
    ).fetchall()


def get_holding(user_id, ore_id):
    """Fetch a specific holding for a user and ore. Returns sqlite3.Row or None."""
    db = get_db()
    return db.execute(
        "SELECT * FROM holdings WHERE user_id = ? AND ore_id = ?",
        (user_id, ore_id)
    ).fetchone()


def create_holding(user_id, ore_id, quantity, price):
    """Create a new holding row."""
    db = get_db()
    db.execute(
        "INSERT INTO holdings (user_id, ore_id, quantity, avg_purchase_price) VALUES (?, ?, ?, ?)",
        (user_id, ore_id, quantity, price)
    )


def update_holding(holding_id, new_quantity, new_avg_price):
    """Update an existing holding's quantity and average price."""
    db = get_db()
    db.execute(
        "UPDATE holdings SET quantity = ?, avg_purchase_price = ? WHERE id = ?",
        (new_quantity, new_avg_price, holding_id)
    )


def delete_holding(holding_id):
    """Delete a holding row (when quantity reaches 0)."""
    db = get_db()
    db.execute("DELETE FROM holdings WHERE id = ?", (holding_id,))


# --- Transaction Model ---

def create_transaction(user_id, ore_id, trade_type, quantity, price_at_trade, total_value):
    """Record a transaction."""
    db = get_db()
    now = datetime.now().isoformat()
    db.execute(
        """INSERT INTO transactions (user_id, ore_id, type, quantity, price_at_trade, total_value, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (user_id, ore_id, trade_type, quantity, price_at_trade, total_value, now)
    )


def get_transactions_by_user(user_id, limit=None):
    """Fetch transactions for a user, most recent first."""
    db = get_db()
    query = """SELECT t.*, o.name as ore_name
               FROM transactions t
               JOIN ores o ON t.ore_id = o.id
               WHERE t.user_id = ? AND t.archived = 0
               ORDER BY t.created_at DESC"""
    if limit:
        query += f" LIMIT {int(limit)}"
    return db.execute(query, (user_id,)).fetchall()


# --- Price History Model ---

def get_price_history(ore_id, limit=50, hours=None):
    """Fetch price history for an ore, oldest first (for charting).
    
    If hours is specified, fetches all points within that time window.
    Otherwise uses the limit parameter.
    """
    db = get_db()
    if hours:
        # Convert fractional hours to minutes for SQLite
        # Use replace() to handle T separator in stored ISO timestamps
        minutes = int(hours * 60)
        cutoff = db.execute(
            "SELECT datetime('now', 'localtime', ?) as cutoff",
            (f'-{minutes} minutes',)
        ).fetchone()['cutoff']
        # Replace space with T to match stored format
        cutoff_t = cutoff.replace(' ', 'T')
        rows = db.execute(
            """SELECT price, movement, created_at
               FROM price_history
               WHERE ore_id = ? AND created_at >= ?
               ORDER BY created_at ASC""",
            (ore_id, cutoff_t)
        ).fetchall()
        return list(rows)
    else:
        rows = db.execute(
            """SELECT price, movement, created_at
               FROM price_history
               WHERE ore_id = ?
               ORDER BY created_at DESC
               LIMIT ?""",
            (ore_id, limit)
        ).fetchall()
        return list(reversed(rows))


# --- Dashboard Model ---

def get_portfolio_value(user_id):
    """Calculate total current market value of a user's holdings."""
    db = get_db()
    row = db.execute(
        """SELECT COALESCE(SUM(h.quantity * o.current_price), 0) as total_value
           FROM holdings h
           JOIN ores o ON h.ore_id = o.id
           WHERE h.user_id = ?""",
        (user_id,)
    ).fetchone()
    return row['total_value']


def get_portfolio_cost(user_id):
    """Calculate total cost basis of a user's holdings."""
    db = get_db()
    row = db.execute(
        """SELECT COALESCE(SUM(h.quantity * h.avg_purchase_price), 0) as total_cost
           FROM holdings h
           WHERE h.user_id = ?""",
        (user_id,)
    ).fetchone()
    return row['total_cost']


def get_top_movers(limit=5):
    """Get ores with the largest absolute price change from base (top movers)."""
    db = get_db()
    return db.execute(
        """SELECT id, name, icon_filename, current_price, base_price,
                  ((current_price - base_price) / base_price * 100) as change_pct
           FROM ores
           ORDER BY ABS(current_price - base_price) / base_price DESC
           LIMIT ?""",
        (limit,)
    ).fetchall()


def get_recent_transactions(user_id, limit=5):
    """Fetch the most recent transactions for the dashboard."""
    return get_transactions_by_user(user_id, limit=limit)


# --- History Model (Paginated) ---

def get_transactions_paginated(user_id, page=1, per_page=20, show_archived=False):
    """Fetch paginated transactions for a user.

    Returns (transactions, total_count).
    """
    db = get_db()
    offset = (page - 1) * per_page

    archive_filter = "" if show_archived else "AND t.archived = 0"

    count_row = db.execute(
        f"""SELECT COUNT(*) as cnt
            FROM transactions t
            WHERE t.user_id = ? {archive_filter}""",
        (user_id,)
    ).fetchone()
    total_count = count_row['cnt']

    rows = db.execute(
        f"""SELECT t.*, o.name as ore_name
            FROM transactions t
            JOIN ores o ON t.ore_id = o.id
            WHERE t.user_id = ? {archive_filter}
            ORDER BY t.created_at DESC
            LIMIT ? OFFSET ?""",
        (user_id, per_page, offset)
    ).fetchall()

    return rows, total_count


# --- Account Management ---

def update_password(user_id, new_password):
    """Update a user's password hash."""
    db = get_db()
    new_hash = generate_password_hash(new_password)
    db.execute("UPDATE users SET password_hash = ? WHERE id = ?", (new_hash, user_id))
    db.commit()


def reset_account(user_id):
    """Reset a user's account: restore default balance, clear holdings, archive transactions."""
    db = get_db()
    default_balance = current_app.config['DEFAULT_BALANCE']

    db.execute("UPDATE users SET balance = ? WHERE id = ?", (default_balance, user_id))
    db.execute("DELETE FROM holdings WHERE user_id = ?", (user_id,))
    db.execute("UPDATE transactions SET archived = 1 WHERE user_id = ? AND archived = 0", (user_id,))
    db.commit()


def delete_account(user_id):
    """Permanently delete a user account and all associated data."""
    db = get_db()

    db.execute("DELETE FROM transactions WHERE user_id = ?", (user_id,))
    db.execute("DELETE FROM holdings WHERE user_id = ?", (user_id,))
    db.execute("DELETE FROM users WHERE id = ?", (user_id,))
    db.commit()


# --- Leaderboard Model ---

def get_leaderboard():
    """Calculate total value (balance + portfolio market value) per user, ranked descending."""
    db = get_db()
    return db.execute(
        """SELECT u.id, u.username,
                  u.balance,
                  COALESCE(SUM(h.quantity * o.current_price), 0) as holdings_value,
                  u.balance + COALESCE(SUM(h.quantity * o.current_price), 0) as total_value
           FROM users u
           LEFT JOIN holdings h ON h.user_id = u.id
           LEFT JOIN ores o ON h.ore_id = o.id
           GROUP BY u.id
           ORDER BY total_value DESC"""
    ).fetchall()
