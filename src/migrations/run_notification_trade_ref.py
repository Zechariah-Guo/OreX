"""Apply the add_notification_trade_ref migration to the live database (idempotent)."""
import os
import sqlite3

DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'data', 'orex.db')

COLUMNS = {
    'transaction_id': 'ALTER TABLE notifications ADD COLUMN transaction_id INTEGER DEFAULT NULL',
    'trigger_price': 'ALTER TABLE notifications ADD COLUMN trigger_price REAL DEFAULT NULL',
}


def run():
    conn = sqlite3.connect(DB_PATH)
    existing = [r[1] for r in conn.execute('PRAGMA table_info(notifications)')]

    for column, statement in COLUMNS.items():
        if column in existing:
            print(f'Skipping: notifications.{column} already exists.')
            continue
        print(f'Executing: {statement}')
        conn.execute(statement)

    conn.commit()
    cols = [r[1] for r in conn.execute('PRAGMA table_info(notifications)')]
    conn.close()
    print(f'Migration completed. notifications columns: {cols}')


if __name__ == '__main__':
    run()
