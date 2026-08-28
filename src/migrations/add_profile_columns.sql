-- Migration: Add profile-related columns to users table
-- Requirements: 7.1, 9.4
-- These columns support the Profile Page feature (avatar, peak net worth, daily bonus)

ALTER TABLE users ADD COLUMN avatar_path TEXT DEFAULT NULL;
ALTER TABLE users ADD COLUMN peak_net_worth REAL NOT NULL DEFAULT 10000;
ALTER TABLE users ADD COLUMN bonus_cycle_day INTEGER NOT NULL DEFAULT 1;
ALTER TABLE users ADD COLUMN last_bonus_collected_date TEXT DEFAULT NULL;
