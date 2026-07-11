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

    # Seed data if ores table is empty
    count = db.execute("SELECT COUNT(*) FROM ores").fetchone()[0]
    if count == 0:
        seed_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'seed.sql')
        with open(seed_path, 'r') as f:
            db.executescript(f.read())

    db.close()

    # Register teardown
    app.teardown_appcontext(close_db)
