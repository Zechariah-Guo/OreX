"""Apply the add_short_open_factor migration to the live database (idempotent).

Adds short_positions.open_factor if it is missing, backfills active rows from their
short_open transaction (bot-aware), and repairs bot rows an earlier version of the
backfill got wrong. Safe to run more than once.

Usage (from the repo root):
    python src/migrations/run_short_open_factor.py
"""
import os
import sqlite3

DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'data', 'orex.db')
MIGRATION_PATH = os.path.join(os.path.dirname(__file__), 'add_short_open_factor.sql')


def _statements(path):
    with open(path, 'r', encoding='utf-8') as f:
        sql = ''.join(line for line in f.readlines() if not line.strip().startswith('--'))
    return [s.strip() for s in sql.split(';') if s.strip()]


def run(db_path=DB_PATH):
    conn = sqlite3.connect(db_path)
    try:
        columns = [r[1] for r in conn.execute('PRAGMA table_info(short_positions)')]
        if not columns:
            raise RuntimeError('short_positions table not found: is this the right database?')
        has_column = 'open_factor' in columns

        for statement in _statements(MIGRATION_PATH):
            label = statement.split('\n', 1)[0][:60]
            if statement.upper().startswith('ALTER TABLE') and has_column:
                print('Skipping: short_positions.open_factor already exists.')
                continue
            cursor = conn.execute(statement)
            if cursor.rowcount >= 0:
                print(f'Executed: {label} ... ({cursor.rowcount} rows)')
            else:
                print(f'Executed: {label}')
        conn.commit()

        left = conn.execute(
            "SELECT COUNT(*) FROM short_positions WHERE status = 'active' AND open_factor IS NULL"
        ).fetchone()[0]
        print(f'Migration completed. Active rows still without open_factor: {left}')
        return left
    finally:
        conn.close()


if __name__ == '__main__':
    run()
