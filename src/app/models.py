"""Data access functions for OreX.

All database queries live here. Functions accept and return
sqlite3.Row objects or dictionaries.
"""

from datetime import datetime

from flask import current_app
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash

from app.database import get_db
from app.storage import get_storage_backend


# --- User Model ---

class User(UserMixin):
    """User class for Flask-Login integration."""

    def __init__(self, id, username, balance):
        self.id = id
        self.username = username
        self.balance = balance


def create_user(username, password):
    """Create a new user with hashed password and default balance. Returns the new user's ID."""
    from app.avatar import get_random_avatar_color

    db = get_db()
    password_hash = generate_password_hash(password)
    default_balance = current_app.config['DEFAULT_BALANCE']
    now = datetime.now().isoformat()
    avatar_color = get_random_avatar_color()

    cursor = db.execute(
        "INSERT INTO users (username, password_hash, balance, created_at, avatar_color) VALUES (?, ?, ?, ?, ?)",
        (username, password_hash, default_balance, now, avatar_color)
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

# Valid transaction type constants.
# The `total_value` field semantics vary by type:
#   - "buy":              total cost paid (quantity × price)
#   - "sell":             total proceeds received (quantity × price)
#   - "short_open":       locked collateral amount frozen from FreeCash
#   - "short_close":      profit/loss amount (positive = profit, negative = loss)
#   - "short_liquidated": profit/loss amount at forced liquidation (typically negative)
TRANSACTION_TYPE_BUY = "buy"
TRANSACTION_TYPE_SELL = "sell"
TRANSACTION_TYPE_SHORT_OPEN = "short_open"
TRANSACTION_TYPE_SHORT_CLOSE = "short_close"
TRANSACTION_TYPE_SHORT_LIQUIDATED = "short_liquidated"

VALID_TRANSACTION_TYPES = (
    TRANSACTION_TYPE_BUY,
    TRANSACTION_TYPE_SELL,
    TRANSACTION_TYPE_SHORT_OPEN,
    TRANSACTION_TYPE_SHORT_CLOSE,
    TRANSACTION_TYPE_SHORT_LIQUIDATED,
)

SHORT_TRANSACTION_TYPES = (
    TRANSACTION_TYPE_SHORT_OPEN,
    TRANSACTION_TYPE_SHORT_CLOSE,
    TRANSACTION_TYPE_SHORT_LIQUIDATED,
)


def create_transaction(user_id, ore_id, trade_type, quantity, price_at_trade, total_value):
    """Record a transaction.

    Args:
        user_id: The player's user ID.
        ore_id: The ore involved in the transaction.
        trade_type: One of VALID_TRANSACTION_TYPES.
        quantity: Number of shares/units.
        price_at_trade: Ore price at time of trade.
        total_value: Semantic meaning depends on trade_type:
            - buy/sell: total cost or proceeds (quantity × price)
            - short_open: locked collateral amount frozen from FreeCash
            - short_close: P/L amount (Locked_Collateral - Short_Value)
            - short_liquidated: P/L amount at forced liquidation
    """
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
    """Calculate total current market value of a user's long holdings only.

    This function intentionally excludes short position equity. For full
    net worth including shorts, use get_net_worth().
    """
    db = get_db()
    row = db.execute(
        """SELECT COALESCE(SUM(h.quantity * o.current_price), 0) as total_value
           FROM holdings h
           JOIN ores o ON h.ore_id = o.id
           WHERE h.user_id = ?""",
        (user_id,)
    ).fetchone()
    return row['total_value']


def get_net_worth(user_id):
    """Calculate total net worth including short position equity.

    Net_Worth = FreeCash + SUM(holdings.qty * ore.price)
                + SUM(locked_collateral - (share_quantity * current_price))
                  for all active short positions.

    When no active short positions exist, the short equity term is 0
    and the result matches the legacy formula (balance + holdings value).
    """
    db = get_db()
    row = db.execute(
        """SELECT
               u.balance +
               COALESCE((SELECT SUM(h.quantity * o2.current_price)
                         FROM holdings h JOIN ores o2 ON h.ore_id = o2.id
                         WHERE h.user_id = u.id), 0) +
               COALESCE((SELECT SUM(sp.locked_collateral - (sp.share_quantity * o3.current_price))
                         FROM short_positions sp JOIN ores o3 ON sp.ore_id = o3.id
                         WHERE sp.user_id = u.id AND sp.status = 'active'), 0)
               AS net_worth
           FROM users u
           WHERE u.id = ?""",
        (user_id,)
    ).fetchone()
    if row is None:
        return 0.0
    return row['net_worth']


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
    """Reset a user's account: restore default balance, clear holdings, archive transactions, and clear Advanced Mode state."""
    db = get_db()
    default_balance = current_app.config['DEFAULT_BALANCE']

    # --- Short position cleanup BEFORE balance restore (Req 14.1, 14.5) ---
    # Delete all short positions without crediting collateral or registering buy pressure
    db.execute("DELETE FROM short_positions WHERE user_id = ?", (user_id,))

    # Archive short-related transactions (Req 14.2)
    db.execute(
        "UPDATE transactions SET archived = 1 WHERE user_id = ? AND type IN ('short_open', 'short_close', 'short_liquidated')",
        (user_id,)
    )

    # Clear all Advanced Mode state and restore default balance (Req 14.3)
    # NOTE: play_time, login_streak, last_streak_date are NOT reset — profile stats persist
    # NOTE: money_theme_unlocked and gold_theme_unlocked are NOT reset (Req 16.4)
    # NOTE: advancements table is NOT touched — achievements persist across resets (Req 16.1)
    # NOTE: avatar_path is NOT cleared — PFP persists across resets (Req 10.1)
    # NOTE: created_at is NOT cleared — account creation date persists (Req 10.4)
    # NOTE: peak_net_worth is NOT cleared — lifetime high persists across resets
    db.execute(
        """UPDATE users
           SET advanced_eligible=0, advanced_purchased=0, advanced_active=0, advanced_toggled_at=NULL,
               balance = ?,
               bonus_cycle_day = 1,
               last_bonus_collected_date = NULL
           WHERE id = ?""",
        (default_balance, user_id)
    )

    # Explicitly delete SL/TP orders before holdings (FK cascade would handle it, but being explicit is safer)
    db.execute(
        "DELETE FROM stop_loss_take_profit WHERE holding_id IN (SELECT id FROM holdings WHERE user_id = ?)",
        (user_id,)
    )

    db.execute("DELETE FROM holdings WHERE user_id = ?", (user_id,))
    db.execute("UPDATE transactions SET archived = 1 WHERE user_id = ? AND archived = 0", (user_id,))
    db.execute("DELETE FROM notifications WHERE user_id = ?", (user_id,))
    db.execute("DELETE FROM tutorial_progress WHERE user_id = ?", (user_id,))
    db.commit()


def delete_account(user_id):
    """Permanently delete a user account and all associated data."""
    db = get_db()

    # Clean up avatar file from storage before deleting the user row
    try:
        user_row = db.execute(
            "SELECT avatar_path FROM users WHERE id = ?", (user_id,)
        ).fetchone()
        if user_row and user_row['avatar_path']:
            storage = get_storage_backend(current_app)
            storage.delete(f"{user_id}.webp")
    except Exception:
        pass

    # Delete short positions before the user row (FK uses ON DELETE RESTRICT)
    db.execute("DELETE FROM short_positions WHERE user_id = ?", (user_id,))

    # Delete notifications if the table exists (defined in notification-system spec)
    try:
        db.execute("DELETE FROM notifications WHERE user_id = ?", (user_id,))
    except Exception:
        pass

    db.execute("DELETE FROM transactions WHERE user_id = ?", (user_id,))
    db.execute("DELETE FROM holdings WHERE user_id = ?", (user_id,))
    db.execute("DELETE FROM backup_codes WHERE user_id = ?", (user_id,))
    db.execute("DELETE FROM users WHERE id = ?", (user_id,))
    db.commit()


# --- 2FA Model ---

def get_2fa_status(user_id):
    """Return the 2FA status for a user: {enabled: bool, encrypted_secret: str|None}."""
    db = get_db()
    row = db.execute(
        "SELECT totp_enabled, totp_secret_encrypted FROM users WHERE id = ?",
        (user_id,)
    ).fetchone()
    if row is None:
        return {'enabled': False, 'encrypted_secret': None}
    return {
        'enabled': bool(row['totp_enabled']),
        'encrypted_secret': row['totp_secret_encrypted']
    }


def enable_2fa(user_id, encrypted_secret):
    """Enable 2FA for a user by setting totp_enabled=1 and storing the encrypted secret."""
    db = get_db()
    db.execute(
        "UPDATE users SET totp_enabled = 1, totp_secret_encrypted = ? WHERE id = ?",
        (encrypted_secret, user_id)
    )
    db.commit()


def disable_2fa(user_id):
    """Disable 2FA for a user: clear secret, disable flag, and delete all backup codes."""
    db = get_db()
    db.execute(
        "UPDATE users SET totp_enabled = 0, totp_secret_encrypted = NULL WHERE id = ?",
        (user_id,)
    )
    db.execute("DELETE FROM backup_codes WHERE user_id = ?", (user_id,))
    db.commit()


def get_encrypted_totp_secret(user_id):
    """Fetch the encrypted TOTP secret for a user. Returns str or None."""
    db = get_db()
    row = db.execute(
        "SELECT totp_secret_encrypted FROM users WHERE id = ?",
        (user_id,)
    ).fetchone()
    if row is None:
        return None
    return row['totp_secret_encrypted']


# --- Leaderboard Model ---

def get_leaderboard():
    """Calculate net worth (balance + portfolio + short equity) per user, ranked descending.

    Uses the updated net worth formula that includes short position equity:
    Net_Worth = FreeCash + SUM(holdings.qty * ore.price)
                + SUM(locked_collateral - share_quantity * current_price)
                  for all active short positions.
    """
    db = get_db()
    return db.execute(
        """SELECT u.id, u.username,
                  u.avatar_path,
                  u.balance,
                  u.advanced_active,
                  u.avatar_color,
                  COALESCE(SUM(h.quantity * o.current_price), 0) as holdings_value,
                  COALESCE((SELECT SUM(sp.locked_collateral - (sp.share_quantity * o3.current_price))
                            FROM short_positions sp
                            JOIN ores o3 ON sp.ore_id = o3.id
                            WHERE sp.user_id = u.id AND sp.status = 'active'), 0) as short_equity,
                  u.balance
                    + COALESCE(SUM(h.quantity * o.current_price), 0)
                    + COALESCE((SELECT SUM(sp.locked_collateral - (sp.share_quantity * o3.current_price))
                                FROM short_positions sp
                                JOIN ores o3 ON sp.ore_id = o3.id
                                WHERE sp.user_id = u.id AND sp.status = 'active'), 0)
                    as total_value
           FROM users u
           LEFT JOIN holdings h ON h.user_id = u.id
           LEFT JOIN ores o ON h.ore_id = o.id
           GROUP BY u.id
           ORDER BY total_value DESC"""
    ).fetchall()


# --- Backup Codes Model ---

def store_backup_codes(user_id, hashed_codes):
    """Insert hashed backup codes into backup_codes table."""
    db = get_db()
    for code_hash in hashed_codes:
        db.execute(
            "INSERT INTO backup_codes (user_id, code_hash, used) VALUES (?, ?, 0)",
            (user_id, code_hash)
        )
    db.commit()


def get_backup_codes(user_id):
    """Fetch all backup code rows for a user (id, code_hash, used)."""
    db = get_db()
    rows = db.execute(
        "SELECT id, code_hash, used FROM backup_codes WHERE user_id = ?",
        (user_id,)
    ).fetchall()
    return [{"id": row["id"], "code_hash": row["code_hash"], "used": row["used"]} for row in rows]


def mark_backup_code_used(code_id):
    """Mark a specific backup code as used."""
    db = get_db()
    db.execute("UPDATE backup_codes SET used = 1 WHERE id = ?", (code_id,))
    db.commit()


def delete_backup_codes(user_id):
    """Remove all backup codes for a user."""
    db = get_db()
    db.execute("DELETE FROM backup_codes WHERE user_id = ?", (user_id,))
    db.commit()


def get_remaining_backup_code_count(user_id):
    """Count unused backup codes for a user."""
    db = get_db()
    row = db.execute(
        "SELECT COUNT(*) as cnt FROM backup_codes WHERE user_id = ? AND used = 0",
        (user_id,)
    ).fetchone()
    return row["cnt"]


# --- Notifications Model ---

def create_notification(user_id, category, message, action_url=None, target_url=None):
    """Create a new notification for a user.

    Validates inputs, inserts a new row with is_read=0, and returns the
    notification ID. The action_url is always set to the notification's own
    inbox detail view (/inbox?selected=<id>) so toast clicks open the inbox entry.

    Args:
        user_id: The target user's ID (must exist in users table).
        category: Any non-empty string categorizing the notification.
        message: The notification message (must not be empty or whitespace-only).
        action_url: Ignored — kept for API compatibility. Always overridden
            with the inbox detail URL.
        target_url: Optional page the inbox detail pane links onward to
            (e.g. '/history'). Stored as-is; None means no link is shown.

    Returns:
        int: The ID of the newly created notification.

    Raises:
        ValueError: If message is empty/whitespace-only or user_id does not exist.
    """
    # Validate message is not empty or whitespace-only
    if not message or not message.strip():
        raise ValueError("Message cannot be empty or whitespace-only")

    # Validate user_id exists in users table
    db = get_db()
    user_row = db.execute("SELECT 1 FROM users WHERE id = ?", (user_id,)).fetchone()
    if user_row is None:
        raise ValueError("User does not exist")

    # Insert notification with is_read=0 (action_url set after we get the ID)
    cursor = db.execute(
        """INSERT INTO notifications (user_id, category, message, action_url, target_url, is_read, created_at)
           VALUES (?, ?, ?, NULL, ?, 0, datetime('now', 'localtime'))""",
        (user_id, category, message, target_url),
    )
    notif_id = cursor.lastrowid

    # Set action_url to point to this notification's inbox detail
    db.execute(
        "UPDATE notifications SET action_url = ? WHERE id = ?",
        (f'/inbox?selected={notif_id}', notif_id),
    )
    db.commit()
    return notif_id


def get_notifications(user_id, filter='all'):
    """Return notifications for a user, filtered by read status, newest first.

    Args:
        user_id: The user's ID.
        filter: One of 'all', 'read', or 'unread'.

    Returns:
        list[Row]: Notifications ordered by id DESC.
    """
    db = get_db()
    if filter == 'read':
        rows = db.execute(
            "SELECT * FROM notifications WHERE user_id = ? AND is_read = 1 ORDER BY id DESC",
            (user_id,),
        ).fetchall()
    elif filter == 'unread':
        rows = db.execute(
            "SELECT * FROM notifications WHERE user_id = ? AND is_read = 0 ORDER BY id DESC",
            (user_id,),
        ).fetchall()
    else:
        rows = db.execute(
            "SELECT * FROM notifications WHERE user_id = ? ORDER BY id DESC",
            (user_id,),
        ).fetchall()
    return rows


def get_notification_detail(notification_id, user_id):
    """Return a single notification owned by the given user, or None.

    Args:
        notification_id: The notification's ID.
        user_id: The user's ID (ownership check).

    Returns:
        Row or None: The notification row if found and owned by user.
    """
    db = get_db()
    row = db.execute(
        "SELECT * FROM notifications WHERE id = ? AND user_id = ?",
        (notification_id, user_id),
    ).fetchone()
    return row


def get_notification_trade(transaction_id, user_id):
    """Return the transaction a trade notification points at, joined with its ore.

    Ownership-checked: returns None unless the transaction belongs to user_id.
    """
    if transaction_id is None:
        return None
    db = get_db()
    return db.execute(
        """SELECT t.id, t.type, t.quantity, t.price_at_trade, t.total_value,
                  o.id AS ore_id, o.name AS ore_name, o.icon_filename
           FROM transactions t
           JOIN ores o ON o.id = t.ore_id
           WHERE t.id = ? AND t.user_id = ?""",
        (transaction_id, user_id),
    ).fetchone()


def has_unread_notifications(user_id):
    """Check if a user has any unread notifications.

    Args:
        user_id: The user's ID.

    Returns:
        bool: True if any is_read=0 notifications exist for the user.
    """
    db = get_db()
    row = db.execute(
        "SELECT 1 FROM notifications WHERE user_id = ? AND is_read = 0 LIMIT 1",
        (user_id,),
    ).fetchone()
    return row is not None


def get_new_notifications_since(user_id, since_id):
    """Return unread notifications with id greater than since_id for a user.

    Used by the polling endpoint to detect new notifications since the last poll.

    Args:
        user_id: The user's ID.
        since_id: The watermark notification ID from the last poll.

    Returns:
        list[Row]: Unread notifications with id > since_id, ordered by id DESC.
    """
    db = get_db()
    rows = db.execute(
        "SELECT * FROM notifications WHERE user_id = ? AND is_read = 0 AND id > ? ORDER BY id DESC",
        (user_id, since_id),
    ).fetchall()
    return rows

def get_pending_toasts(user_id):
    """Return notifications that haven't been toasted yet.

    Returns notifications with toasted=0 for the given user, ordered by id ASC
    (oldest first so toasts appear in chronological order).

    Args:
        user_id: The user's ID.

    Returns:
        list[Row]: Notifications with toasted=0, ordered by id ASC.
    """
    db = get_db()
    rows = db.execute(
        "SELECT * FROM notifications WHERE user_id = ? AND toasted = 0 ORDER BY id ASC",
        (user_id,),
    ).fetchall()
    return rows

def mark_notifications_toasted(notification_ids):
    """Mark notifications as toasted so they won't fire again.

    Args:
        notification_ids: List of notification IDs to mark as toasted.
    """
    if not notification_ids:
        return
    db = get_db()
    placeholders = ",".join("?" * len(notification_ids))
    db.execute(
        f"UPDATE notifications SET toasted = 1 WHERE id IN ({placeholders})",
        notification_ids,
    )
    db.commit()

def mark_notification_read(notification_id, user_id):
    """Mark a single notification as read for the owning user.

    Sets is_read=1 only if the notification belongs to the specified user.

    Args:
        notification_id: The notification's ID.
        user_id: The user's ID (ownership check).

    Returns:
        bool: True if the notification was found, owned by user, and updated.
    """
    db = get_db()
    cursor = db.execute(
        "UPDATE notifications SET is_read = 1 WHERE id = ? AND user_id = ?",
        (notification_id, user_id),
    )
    db.commit()
    return cursor.rowcount > 0


def delete_notification(notification_id, user_id):
    """Delete a single notification owned by the specified user.

    Only deletes if the notification belongs to the user, preventing
    cross-user manipulation.

    Args:
        notification_id: The notification's ID.
        user_id: The user's ID (ownership check).

    Returns:
        bool: True if the notification was found, owned by user, and deleted.
    """
    db = get_db()
    cursor = db.execute(
        "DELETE FROM notifications WHERE id = ? AND user_id = ?",
        (notification_id, user_id),
    )
    db.commit()
    return cursor.rowcount > 0


def mark_notifications_read(notification_ids, user_id):
    """Mark the given notifications as read, limited to those the user owns.

    Returns:
        int: How many notifications were updated.
    """
    if not notification_ids:
        return 0
    db = get_db()
    placeholders = ",".join("?" * len(notification_ids))
    cursor = db.execute(
        f"UPDATE notifications SET is_read = 1 WHERE user_id = ? AND is_read = 0 AND id IN ({placeholders})",
        [user_id, *notification_ids],
    )
    db.commit()
    return cursor.rowcount


def delete_notifications(notification_ids, user_id):
    """Delete the given notifications, limited to those the user owns.

    Returns:
        int: How many notifications were deleted.
    """
    if not notification_ids:
        return 0
    db = get_db()
    placeholders = ",".join("?" * len(notification_ids))
    cursor = db.execute(
        f"DELETE FROM notifications WHERE user_id = ? AND id IN ({placeholders})",
        [user_id, *notification_ids],
    )
    db.commit()
    return cursor.rowcount


_NOTIFICATION_ICON_PATHS = {
    "trophy": "M280-120v-80h160v-124q-49-11-87.5-41.5T296-442q-75-9-125.5-65.5T120-640v-40q0-33 23.5-56.5T200-760h80v-80h400v80h80q33 0 56.5 23.5T840-680v40q0 76-50.5 132.5T664-442q-18 46-56.5 76.5T520-324v124h160v80H280Zm0-408v-152h-80v40q0 38 22 68.5t58 43.5Zm285 93q35-35 35-85v-240H360v240q0 50 35 85t85 35q50 0 85-35Zm115-93q36-13 58-43.5t22-68.5v-40h-80v152Zm-200-52Z",
    "warning": "m40-120 440-760 440 760H40Zm138-80h604L480-720 178-200Zm330.5-51.5Q520-263 520-280t-11.5-28.5Q497-320 480-320t-28.5 11.5Q440-297 440-280t11.5 28.5Q463-240 480-240t28.5-11.5ZM440-360h80v-200h-80v200Zm40-100Z",
    "dollar": "M441-120v-86q-53-12-91.5-46T293-348l74-30q15 48 44.5 73t77.5 25q41 0 69.5-18.5T587-356q0-35-22-55.5T463-458q-86-27-118-64.5T313-614q0-65 42-101t86-41v-84h80v84q50 8 82.5 36.5T651-650l-74 32q-12-32-34-48t-60-16q-44 0-67 19.5T393-614q0 33 30 52t104 40q69 20 104.5 63.5T667-358q0 71-42 108t-104 46v84h-80Z",
    "bell": "M160-200v-80h80v-280q0-83 50-147.5T420-792v-28q0-25 17.5-42.5T480-880q25 0 42.5 17.5T540-820v28q80 20 130 84.5T720-560v280h80v80H160Zm320-300Zm0 420q-33 0-56.5-23.5T400-160h160q0 33-23.5 56.5T480-80ZM320-280h320v-280q0-66-47-113t-113-47q-66 0-113 47t-47 113v280Z",
}

_NOTIFICATION_STYLES = {
    "achievement": ("flash--achievement", _NOTIFICATION_ICON_PATHS["trophy"], 5000),
    "advancement": ("flash--achievement", _NOTIFICATION_ICON_PATHS["trophy"], 5000),
    "liquidation": ("flash--liquidation", _NOTIFICATION_ICON_PATHS["warning"], 5000),
    "stop_loss": ("flash--stop-loss", _NOTIFICATION_ICON_PATHS["bell"], 3000),
    "take_profit": ("flash--take-profit", _NOTIFICATION_ICON_PATHS["bell"], 3000),
    "bonus": ("flash--bonus", _NOTIFICATION_ICON_PATHS["dollar"], 5000),
}

_DEFAULT_NOTIFICATION_STYLE = ("flash--default", _NOTIFICATION_ICON_PATHS["bell"], 3000)


def get_notification_style(category):
    """Return (css_class, icon, duration) tuple for a notification category.

    Maps category strings to their visual presentation properties:
    - css_class: CSS modifier class for toast/inbox styling
    - icon: Material Design icon name
    - duration: Toast display duration in milliseconds

    Args:
        category: The notification category string.

    Returns:
        Tuple of (css_class, icon, duration).
    """
    return _NOTIFICATION_STYLES.get(category, _DEFAULT_NOTIFICATION_STYLE)

