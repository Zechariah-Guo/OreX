-- Migration: Add tutorial_progress table for the Tutorial System
-- Requirements: 11.1, 11.2
-- Idempotent: safe to run on a DB that already has the table.

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

CREATE INDEX IF NOT EXISTS idx_tutorial_progress_user ON tutorial_progress(user_id);
CREATE INDEX IF NOT EXISTS idx_tutorial_progress_user_status ON tutorial_progress(user_id, status);
