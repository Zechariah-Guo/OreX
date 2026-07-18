-- Migration: Add short_positions table for the Shorting System
-- Applies to existing databases that already have users and ores tables

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

CREATE INDEX IF NOT EXISTS idx_short_positions_user ON short_positions(user_id);
CREATE INDEX IF NOT EXISTS idx_short_positions_status ON short_positions(status);
CREATE INDEX IF NOT EXISTS idx_short_positions_ore_status ON short_positions(ore_id, status);
