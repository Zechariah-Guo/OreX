-- Migration: Add Advanced Mode support
-- Requirements: 6.1, 6.2, 4.5, 3.4

-- Add advanced mode columns to users table
ALTER TABLE users ADD COLUMN advanced_eligible INTEGER NOT NULL DEFAULT 0;
ALTER TABLE users ADD COLUMN advanced_purchased INTEGER NOT NULL DEFAULT 0;
ALTER TABLE users ADD COLUMN advanced_active INTEGER NOT NULL DEFAULT 0;
ALTER TABLE users ADD COLUMN advanced_toggled_at TEXT DEFAULT NULL;

-- Stop Loss / Take Profit orders
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

CREATE INDEX IF NOT EXISTS idx_sltp_holding ON stop_loss_take_profit(holding_id);
CREATE INDEX IF NOT EXISTS idx_sltp_active ON stop_loss_take_profit(active);
