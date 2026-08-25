"""Drop a test user by username without needing to log in.

Usage:
    python scripts/drop_user.py <username>
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from app import create_app
from app.models import delete_account, get_db


def drop_user(username):
    app = create_app()
    with app.app_context():
        db = get_db()
        row = db.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone()
        if not row:
            print(f"User '{username}' not found.")
            sys.exit(1)
        delete_account(row['id'])
        print(f"Deleted user '{username}' (id={row['id']}).")


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Usage: python scripts/drop_user.py <username>")
        sys.exit(1)
    drop_user(sys.argv[1])
