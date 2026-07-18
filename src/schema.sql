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
    advanced_toggled_at TEXT DEFAULT NULL
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
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE RESTRICT,
    FOREIGN KEY (ore_id) REFERENCES ores(id) ON DELETE RESTRICT
);

-- Indexes
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
