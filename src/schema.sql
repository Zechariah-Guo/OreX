-- OreX Database Schema

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    balance REAL NOT NULL DEFAULT 10000,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    last_login TEXT,
    totp_enabled INTEGER NOT NULL DEFAULT 0,
    totp_secret_encrypted TEXT,
    advanced_eligible INTEGER NOT NULL DEFAULT 0,
    advanced_purchased INTEGER NOT NULL DEFAULT 0,
    advanced_active INTEGER NOT NULL DEFAULT 0,
    advanced_toggled_at TEXT DEFAULT NULL,
    play_time INTEGER NOT NULL DEFAULT 0,
    login_streak INTEGER NOT NULL DEFAULT 0,
    last_streak_date TEXT DEFAULT NULL,
    money_theme_unlocked INTEGER NOT NULL DEFAULT 0,
    gold_theme_unlocked INTEGER NOT NULL DEFAULT 0,
    avatar_color TEXT DEFAULT NULL,
    avatar_path TEXT DEFAULT NULL,
    peak_net_worth REAL NOT NULL DEFAULT 10000,
    bonus_cycle_day INTEGER NOT NULL DEFAULT 1,
    last_bonus_collected_date TEXT DEFAULT NULL,
    session_version INTEGER NOT NULL DEFAULT 0,
    suspended_at TEXT DEFAULT NULL,
    suspended_reason TEXT DEFAULT NULL
);

CREATE TABLE IF NOT EXISTS ores (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    description TEXT,
    icon_filename TEXT,
    current_price REAL NOT NULL,
    base_price REAL NOT NULL,
    price_floor REAL NOT NULL,
    price_ceiling REAL NOT NULL,
    volatility REAL NOT NULL,
    price_change_range TEXT NOT NULL,
    base_probabilities TEXT NOT NULL,
    trend_log TEXT NOT NULL DEFAULT '["hold","hold","hold","hold","hold"]'
);

CREATE TABLE IF NOT EXISTS holdings (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL,
    ore_id INTEGER NOT NULL,
    quantity INTEGER NOT NULL,
    avg_purchase_price REAL NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(id),
    FOREIGN KEY (ore_id) REFERENCES ores(id)
);

-- Supported transaction types (freeform TEXT, no CHECK constraint):
--   "buy"              — regular ore purchase; total_value = quantity × price (cost paid)
--   "sell"             — regular ore sale; total_value = quantity × price (proceeds received)
--   "short_open"       — short position opened; total_value = locked collateral amount
--   "short_close"      — short position closed voluntarily or via SL/TP; total_value = P/L amount
--   "short_liquidated" — short position forcefully liquidated; total_value = P/L amount
CREATE TABLE IF NOT EXISTS transactions (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL,
    ore_id INTEGER NOT NULL,
    type TEXT NOT NULL,
    quantity INTEGER NOT NULL,
    price_at_trade REAL NOT NULL,
    total_value REAL NOT NULL,
    archived INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (user_id) REFERENCES users(id),
    FOREIGN KEY (ore_id) REFERENCES ores(id)
);

CREATE TABLE IF NOT EXISTS price_history (
    id INTEGER PRIMARY KEY,
    ore_id INTEGER NOT NULL,
    price REAL NOT NULL,
    movement TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (ore_id) REFERENCES ores(id)
);

CREATE TABLE IF NOT EXISTS backup_codes (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL,
    code_hash TEXT NOT NULL,
    used INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

-- One optional, single-use account recovery key per user (hash only).
CREATE TABLE IF NOT EXISTS recovery_keys (
    user_id INTEGER PRIMARY KEY,
    key_hash TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS stop_loss_take_profit (
    id INTEGER PRIMARY KEY,
    holding_id INTEGER NOT NULL,
    stop_loss REAL DEFAULT NULL,
    take_profit REAL DEFAULT NULL,
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    triggered_at TEXT DEFAULT NULL,
    FOREIGN KEY (holding_id) REFERENCES holdings(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS short_positions (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL,
    ore_id INTEGER NOT NULL,
    share_quantity INTEGER NOT NULL CHECK (share_quantity >= 1 AND share_quantity <= 10000),
    entry_price REAL NOT NULL CHECK (entry_price > 0),
    locked_collateral REAL NOT NULL CHECK (locked_collateral > 0),
    stop_loss_price REAL DEFAULT NULL,
    take_profit_price REAL DEFAULT NULL,
    cumulative_fees_paid REAL NOT NULL DEFAULT 0.0,
    opened_at TEXT NOT NULL DEFAULT (datetime('now')),
    closed_at TEXT DEFAULT NULL,
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'closed')),
    -- 1 for a throwaway short opened by the Advanced tutorial so its pages show
    -- live data. Excluded from fees, P/L, advancements and leaderboard money, and
    -- always cleaned up by the tutorial; see app/tutorial/demo.py.
    is_demo INTEGER NOT NULL DEFAULT 0,
    -- (1 + collateral multiplier) fixed at open. The margin-call phase scales
    -- the vault as price x shares x open_factor; it must NOT be derived from
    -- locked_collateral, which grows with top-ups and would compound.
    open_factor REAL NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE RESTRICT,
    FOREIGN KEY (ore_id) REFERENCES ores(id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS advancements (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL,
    advancement_key TEXT NOT NULL,
    earned_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    UNIQUE(user_id, advancement_key),
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS notifications (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL,
    category TEXT NOT NULL,
    message TEXT NOT NULL,
    action_url TEXT DEFAULT NULL,
    target_url TEXT DEFAULT NULL,
    -- Trade notifications (SL/TP, liquidation): the transaction row they describe,
    -- and the SL/TP price the player set. NULL for every other notification.
    transaction_id INTEGER DEFAULT NULL,
    trigger_price REAL DEFAULT NULL,
    is_read INTEGER NOT NULL DEFAULT 0,
    toasted INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS tutorial_progress (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL,
    track_id TEXT NOT NULL,
    current_step_index INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'not_started'
        CHECK (status IN ('not_started', 'in_progress', 'completed', 'dismissed')),
    last_updated TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    UNIQUE(user_id, track_id),
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

-- Web Push (opt-in). One row per browser/device that enabled notifications.
-- A subscription belongs to the account that created it.
CREATE TABLE IF NOT EXISTS push_subscriptions (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL,
    endpoint TEXT NOT NULL UNIQUE,
    p256dh TEXT NOT NULL,
    auth TEXT NOT NULL,
    user_agent TEXT DEFAULT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    last_success_at TEXT DEFAULT NULL,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

-- Per-account push settings. No row = every category on and never seen present.
-- last_visible_at is the unix time of the player's latest poll from a visible
-- page (stored in the database so every process and the engine thread agree).
CREATE TABLE IF NOT EXISTS push_settings (
    user_id INTEGER PRIMARY KEY,
    notify_take_profit INTEGER NOT NULL DEFAULT 1,
    notify_stop_loss INTEGER NOT NULL DEFAULT 1,
    notify_liquidation INTEGER NOT NULL DEFAULT 1,
    notify_bonus INTEGER NOT NULL DEFAULT 1,
    notify_achievement INTEGER NOT NULL DEFAULT 1,
    last_visible_at REAL NOT NULL DEFAULT 0,
    last_test_at REAL NOT NULL DEFAULT 0,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

-- Presence per page instance. client_id is a random id the page keeps in
-- sessionStorage ('' for a poll that sends none). The player counts as present
-- while any row is recent. A page that is hidden or closed deletes its own row.
CREATE TABLE IF NOT EXISTS push_presence (
    user_id INTEGER NOT NULL,
    client_id TEXT NOT NULL,
    seen_at REAL NOT NULL,
    PRIMARY KEY (user_id, client_id),
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

-- A notification that was claimed for push. The PRIMARY KEY makes the claim
-- atomic (INSERT OR IGNORE), so two engine threads or processes never both
-- send it. A separate table, not a column, so existing databases need no ALTER.
CREATE TABLE IF NOT EXISTS notification_pushes (
    notification_id INTEGER PRIMARY KEY,
    pushed_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    FOREIGN KEY (notification_id) REFERENCES notifications(id) ON DELETE CASCADE
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_push_subscriptions_user ON push_subscriptions(user_id);
CREATE INDEX IF NOT EXISTS idx_notifications_user_read ON notifications(user_id, is_read);
CREATE INDEX IF NOT EXISTS idx_notifications_user_id_desc ON notifications(user_id, id DESC);
CREATE INDEX IF NOT EXISTS idx_holdings_user ON holdings(user_id);
CREATE INDEX IF NOT EXISTS idx_holdings_ore ON holdings(ore_id);
CREATE INDEX IF NOT EXISTS idx_transactions_user ON transactions(user_id);
CREATE INDEX IF NOT EXISTS idx_transactions_ore ON transactions(ore_id);
CREATE INDEX IF NOT EXISTS idx_price_history_ore ON price_history(ore_id);
CREATE INDEX IF NOT EXISTS idx_price_history_created ON price_history(created_at);
CREATE INDEX IF NOT EXISTS idx_backup_codes_user ON backup_codes(user_id);
CREATE INDEX IF NOT EXISTS idx_sltp_holding ON stop_loss_take_profit(holding_id);
CREATE INDEX IF NOT EXISTS idx_sltp_active ON stop_loss_take_profit(active);
CREATE INDEX IF NOT EXISTS idx_short_positions_user ON short_positions(user_id);
CREATE INDEX IF NOT EXISTS idx_short_positions_status ON short_positions(status);
CREATE INDEX IF NOT EXISTS idx_short_positions_ore_status ON short_positions(ore_id, status);
CREATE INDEX IF NOT EXISTS idx_advancements_user ON advancements(user_id);
CREATE INDEX IF NOT EXISTS idx_tutorial_progress_user ON tutorial_progress(user_id);
CREATE INDEX IF NOT EXISTS idx_tutorial_progress_user_status ON tutorial_progress(user_id, status);
