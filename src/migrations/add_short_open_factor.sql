-- Migration: store the open-time collateral factor on short_positions.
-- The margin-call phase used to derive (1 + multiplier) from locked_collateral,
-- which compounds as the vault is topped up. Store it once at open instead.
--
-- Apply with: python src/migrations/run_short_open_factor.py
-- The runner is idempotent (it skips the ALTER if the column exists), so this
-- file can be re-applied safely to repair data.

ALTER TABLE short_positions ADD COLUMN open_factor REAL DEFAULT NULL;

-- Backfill from the matching short_open transaction, so vault-at-open / (entry x shares)
-- = 1 + multiplier. What the transaction's total_value holds differs by who opened:
--   players: the full vault            -> factor = total_value / (entry x shares)
--   bots:    only the margin (bots.py) -> factor = 1 + total_value / (entry x shares)
-- Takes the latest matching open for that user and ore.
UPDATE short_positions
SET open_factor = (
    SELECT t.total_value / (short_positions.entry_price * short_positions.share_quantity)
           + CASE WHEN u.password_hash = 'BOT_NO_LOGIN' THEN 1.0 ELSE 0.0 END
    FROM transactions t
    JOIN users u ON u.id = t.user_id
    WHERE t.user_id = short_positions.user_id
      AND t.ore_id = short_positions.ore_id
      AND t.type = 'short_open'
      AND t.quantity = short_positions.share_quantity
      AND t.price_at_trade = short_positions.entry_price
    ORDER BY t.id DESC
    LIMIT 1
)
WHERE open_factor IS NULL AND status = 'active';

-- Repair: an earlier version of this backfill treated a bot's margin as if it were
-- the vault, storing the multiplier (about 0.5) instead of 1 + multiplier (about 1.5).
-- Only rows whose factor EQUALS that uncorrected value are touched. A correctly stored
-- bot row differs from it by about 1, so it keeps its exact value (the transaction's
-- margin is rounded to cents, so recomputing it would only make it slightly less exact).
-- Re-running is harmless.
UPDATE short_positions
SET open_factor = 1.0 + (
    SELECT t.total_value / (short_positions.entry_price * short_positions.share_quantity)
    FROM transactions t
    WHERE t.user_id = short_positions.user_id
      AND t.ore_id = short_positions.ore_id
      AND t.type = 'short_open'
      AND t.quantity = short_positions.share_quantity
      AND t.price_at_trade = short_positions.entry_price
    ORDER BY t.id DESC
    LIMIT 1
)
WHERE status = 'active'
  AND open_factor IS NOT NULL
  AND user_id IN (SELECT id FROM users WHERE password_hash = 'BOT_NO_LOGIN')
  AND ABS(open_factor - (
    SELECT t.total_value / (short_positions.entry_price * short_positions.share_quantity)
    FROM transactions t
    WHERE t.user_id = short_positions.user_id
      AND t.ore_id = short_positions.ore_id
      AND t.type = 'short_open'
      AND t.quantity = short_positions.share_quantity
      AND t.price_at_trade = short_positions.entry_price
    ORDER BY t.id DESC
    LIMIT 1
  )) < 0.0001;

-- Anything unmatched (e.g. old rows with no matching transaction) falls back to the
-- base 1.5 factor. Only active rows matter: the engine never reads open_factor for
-- closed ones, and skipping them keeps this fast on a large transactions table.
UPDATE short_positions SET open_factor = 1.5
WHERE open_factor IS NULL AND status = 'active';
