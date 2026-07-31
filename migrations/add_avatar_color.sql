-- Add avatar_color column to users table for persistent avatar background colours
ALTER TABLE users ADD COLUMN avatar_color TEXT DEFAULT NULL;
