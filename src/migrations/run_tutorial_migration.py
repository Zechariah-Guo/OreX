"""Run the add_tutorial_progress migration against the live database.

Idempotent (CREATE ... IF NOT EXISTS), so existing data is never touched.
Back up src/data/orex.db before running this against a database you care about.
"""
import os
import sqlite3

DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'data', 'orex.db')
MIGRATION_PATH = os.path.join(os.path.dirname(__file__), 'add_tutorial_progress.sql')


def run():
    conn = sqlite3.connect(DB_PATH)
    with open(MIGRATION_PATH, 'r') as f:
        conn.executescript(f.read())
    conn.close()
    print("Migration completed successfully.")

    # Verify
    conn = sqlite3.connect(DB_PATH)
    cols = [r[1] for r in conn.execute('PRAGMA table_info(tutorial_progress)')]
    indexes = [r[1] for r in conn.execute('PRAGMA index_list(tutorial_progress)')]
    print(f"tutorial_progress columns: {cols}")
    print(f"tutorial_progress indexes: {indexes}")
    conn.close()


if __name__ == '__main__':
    run()
