-- Migration: Add Advancements System support
-- Requirements: 1.1, 1.2, 1.3, 1.4, 2.1, 3.1, 13.4

-- Add play time and login streak tracking columns to users table
ALTER TABLE users ADD COLUMN play_time INTEGER NOT NULL DEFAULT 0;
ALTER TABLE users ADD COLUMN login_streak INTEGER NOT NULL DEFAULT 0;
ALTER TABLE users ADD COLUMN last_streak_date TEXT DEFAULT NULL;

-- Add theme unlock flags to users table
ALTER TABLE users ADD COLUMN money_theme_unlocked INTEGER NOT NULL DEFAULT 0;
ALTER TABLE users ADD COLUMN gold_theme_unlocked INTEGER NOT NULL DEFAULT 0;

-- Advancements table
CREATE TABLE IF NOT EXISTS advancements (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL,
    advancement_key TEXT NOT NULL,
    earned_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    UNIQUE(user_id, advancement_key),
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_advancements_user ON advancements(user_id);
