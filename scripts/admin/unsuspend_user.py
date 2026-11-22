"""Lift a suspension set by suspend_user.py.

The player can sign in again and reappears on the leaderboard.

Usage:
    python scripts/admin/unsuspend_user.py <username>
"""

import argparse

from _admin_common import create_script_app, find_player

from app.models import get_db


def unsuspend_user(username, app=None):
    app = app or create_script_app()
    with app.app_context():
        db = get_db()
        row = find_player(db, username)
        if not row['suspended_at']:
            print(f"User '{username}' is not suspended. No change.")
            return
        db.execute(
            "UPDATE users SET suspended_at = NULL, suspended_reason = NULL WHERE id = ?",
            (row['id'],),
        )
        db.commit()
        print(f"Unsuspended user '{username}' (id={row['id']}).")


def main(argv=None, app=None):
    parser = argparse.ArgumentParser(description="Lift a player's suspension.")
    parser.add_argument('username')
    args = parser.parse_args(argv)
    unsuspend_user(args.username, app=app)


if __name__ == '__main__':
    main()
