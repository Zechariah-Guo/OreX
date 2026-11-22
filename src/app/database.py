import os
import sqlite3

from flask import g, current_app


def get_db():
    """Get a database connection, storing it on Flask's g object for the request."""
    if 'db' not in g:
        g.db = sqlite3.connect(current_app.config['DATABASE_PATH'])
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA journal_mode=WAL")
        g.db.execute("PRAGMA foreign_keys=ON")
    return g.db


def close_db(e=None):
    """Close the database connection at the end of the request."""
    db = g.pop('db', None)
    if db is not None:
        db.close()


def init_db(app):
    """Create tables if missing and seed data if ores table is empty."""
    # Ensure the data directory exists
    db_path = app.config['DATABASE_PATH']
    os.makedirs(os.path.dirname(db_path), exist_ok=True)

    # Connect directly (outside of request context)
    db = sqlite3.connect(db_path)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")

    # Read and execute schema
    schema_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'schema.sql')
    with open(schema_path, 'r') as f:
        db.executescript(f.read())

    # Columns added after a database was first created (CREATE TABLE IF NOT EXISTS
    # does not add them). Idempotent: each is added only when missing.
    user_columns = {r[1] for r in db.execute("PRAGMA table_info(users)")}
    if 'session_version' not in user_columns:
        db.execute("ALTER TABLE users ADD COLUMN session_version INTEGER NOT NULL DEFAULT 0")
        db.commit()
    # Account suspension (scripts/admin/suspend_user.py): NULL = not suspended.
    if 'suspended_at' not in user_columns:
        db.execute("ALTER TABLE users ADD COLUMN suspended_at TEXT DEFAULT NULL")
        db.execute("ALTER TABLE users ADD COLUMN suspended_reason TEXT DEFAULT NULL")
        db.commit()

    # push_settings.notify_sltp was split into notify_take_profit and
    # notify_stop_loss: players who had it off get both off. The old column
    # stays (unused) on existing databases.
    push_columns = {r[1] for r in db.execute("PRAGMA table_info(push_settings)")}
    if 'notify_take_profit' not in push_columns:
        db.execute("ALTER TABLE push_settings ADD COLUMN notify_take_profit INTEGER NOT NULL DEFAULT 1")
        db.execute("ALTER TABLE push_settings ADD COLUMN notify_stop_loss INTEGER NOT NULL DEFAULT 1")
        if 'notify_sltp' in push_columns:
            db.execute("UPDATE push_settings SET notify_take_profit = notify_sltp, notify_stop_loss = notify_sltp")
        db.commit()

    # Seed data if ores table is empty
    count = db.execute("SELECT COUNT(*) FROM ores").fetchone()[0]
    if count == 0:
        seed_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'seed.sql')
        with open(seed_path, 'r') as f:
            db.executescript(f.read())

    db.close()

    # Register teardown
    app.teardown_appcontext(close_db)
