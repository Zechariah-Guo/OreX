"""Rename a player (for example to remove an offensive username).

The new name must pass the registration rules (3-20 letters, numbers and
underscores) and must not be taken. Registration compares names exactly (case
sensitive); this script also refuses a name that matches another player ignoring
case, so two profile URLs can never be ambiguous.

The player is signed out everywhere (session_version is raised) and signs in with
the new name. Nothing else stores the username: the avatar file is named by user
id, notifications hold no name, and the leaderboard is computed live.

Usage:
    python scripts/admin/rename_user.py <old_username> <new_username>
"""

import argparse
import sys

from _admin_common import create_script_app, find_player

from app.models import get_db
from app.utils.validation import validate_username


def rename_user(old, new, app=None):
    app = app or create_script_app()
    with app.app_context():
        db = get_db()
        row = find_player(db, old)

        valid, error = validate_username(new)
        if not valid:
            print(f"Invalid new username: {error}")
            sys.exit(1)
        if new == old:
            print("The new username is the same as the old one.")
            sys.exit(1)
        clash = db.execute(
            "SELECT username FROM users WHERE username = ? COLLATE NOCASE AND id != ?",
            (new, row['id']),
        ).fetchone()
        if clash:
            print(f"Username '{clash['username']}' is already taken.")
            sys.exit(1)

        db.execute(
            "UPDATE users SET username = ?, session_version = session_version + 1 WHERE id = ?",
            (new, row['id']),
        )
        db.commit()
        print(f"Renamed '{old}' to '{new}' (id={row['id']}).")
        print("Changed: users.username, users.session_version (the player is signed out on every device).")
        print("Nothing else stores the username. The player signs in with the new name; the password is unchanged.")


def main(argv=None, app=None):
    parser = argparse.ArgumentParser(description="Rename a player.")
    parser.add_argument('old_username')
    parser.add_argument('new_username')
    args = parser.parse_args(argv)
    rename_user(args.old_username, args.new_username, app=app)


if __name__ == '__main__':
    main()
