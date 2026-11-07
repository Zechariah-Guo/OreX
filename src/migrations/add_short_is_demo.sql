-- Migration: add is_demo flag to short_positions
-- Supports the Advanced tutorial's throwaway "demo short" (see app/tutorial/demo.py).
-- A demo short exists only to populate the Advanced pages during the tour and is
-- always cleaned up; the flag keeps it out of fees, P/L, advancements and the
-- leaderboard, and lets cleanup target it precisely.

ALTER TABLE short_positions ADD COLUMN is_demo INTEGER NOT NULL DEFAULT 0;
