"""Run the add_profile_columns migration against the live database."""
import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'data', 'orex.db')
MIGRATION_PATH = os.path.join(os.path.dirname(__file__), 'add_profile_columns.sql')


def run():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Check which columns already exist
    existing = [r[1] for r in cursor.execute('PRAGMA table_info(users)')]
    print(f"Existing columns: {existing}")

    with open(MIGRATION_PATH, 'r') as f:
        lines = f.readlines()

    # Filter out comment-only lines and join
    sql_lines = [l for l in lines if not l.strip().startswith('--')]
    sql = ''.join(sql_lines)

    for statement in sql.split(';'):
        statement = statement.strip()
        if not statement:
            continue

        # Extract column name to check if already exists
        col_name = None
        if 'ADD COLUMN' in statement:
            parts = statement.split('ADD COLUMN')[1].strip().split()
            col_name = parts[0]

        if col_name and col_name in existing:
            print(f"Skipping (already exists): {col_name}")
            continue

        print(f"Executing: {statement[:80]}...")
        cursor.execute(statement)

    conn.commit()
    conn.close()
    print("Migration completed successfully.")

    # Verify
    conn = sqlite3.connect(DB_PATH)
    cols = [r[1] for r in conn.execute('PRAGMA table_info(users)')]
    print(f"Updated columns: {cols}")
    conn.close()


if __name__ == '__main__':
    run()
