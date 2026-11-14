-- Migration: link trade notifications to the trade they describe
-- transaction_id: the transactions row for an SL/TP trigger or forced liquidation
--                 (ore, shares, fill price, side, P/L), used by the inbox detail panel.
-- trigger_price:  the Stop Loss / Take Profit price the player set (not stored on the
--                 transaction). NULL for liquidations and all non-trade notifications.
-- Older notifications keep NULL in both and fall back to the generic detail layout.

ALTER TABLE notifications ADD COLUMN transaction_id INTEGER DEFAULT NULL;
ALTER TABLE notifications ADD COLUMN trigger_price REAL DEFAULT NULL;
