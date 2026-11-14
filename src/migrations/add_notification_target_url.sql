-- Migration: add target_url to notifications
-- action_url is the toast click target (always the notification's own inbox entry).
-- target_url is the page the inbox detail pane links onward to (e.g. /history,
-- /settings, /profile). NULL means the detail pane shows no link.

ALTER TABLE notifications ADD COLUMN target_url TEXT DEFAULT NULL;
