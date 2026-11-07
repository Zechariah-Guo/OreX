"""Apply the add_short_is_demo migration to the live database (idempotent)."""
import os
import sqlite3

DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'data', 'orex.db')
MIGRATION_PATH = os.path.join(os.path.dirname(__file__), 'add_short_is_demo.sql')


def run():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    existing = [r[1] for r in cursor.execute('PRAGMA table_info(short_positions)')]
    if 'is_demo' in existing:
        print('Skipping: short_positions.is_demo already exists.')
        conn.close()
        return

    with open(MIGRATION_PATH, 'r') as f:
        sql = ''.join(l for l in f.readlines() if not l.strip().startswith('--'))

    for statement in (s.strip() for s in sql.split(';')):
        if statement:
            print(f'Executing: {statement[:80]}...')
            cursor.execute(statement)

    conn.commit()
    cols = [r[1] for r in conn.execute('PRAGMA table_info(short_positions)')]
    conn.close()
    print(f'Migration completed. short_positions columns: {cols}')


if __name__ == '__main__':
    run()
