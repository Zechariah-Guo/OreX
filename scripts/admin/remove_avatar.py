"""Remove a player's uploaded avatar (for example an offensive picture).

Deletes the file through the configured storage backend (local folder or Oracle
Object Storage, STORAGE_BACKEND) and clears users.avatar_path, so the player
falls back to the coloured initials circle. The player can upload a new one.

Usage:
    python scripts/admin/remove_avatar.py <username>
"""

import argparse
import sys

from _admin_common import create_script_app, find_player

from app.models import get_db
from app.storage import get_storage_backend


def remove_avatar(username, app=None):
    app = app or create_script_app()
    with app.app_context():
        db = get_db()
        row = find_player(db, username)
        if not row['avatar_path']:
            print(f"User '{username}' has no uploaded avatar. Nothing to do.")
            return

        storage = get_storage_backend(app)
        filename = f"{row['id']}.webp"  # same name the upload route uses
        try:
            deleted = storage.delete(filename)
        except Exception as exc:
            print(f"Could not delete {filename} from storage: {exc}")
            print("avatar_path was left unchanged.")
            sys.exit(1)

        db.execute("UPDATE users SET avatar_path = NULL WHERE id = ?", (row['id'],))
        db.commit()
        if deleted:
            print(f"Removed avatar for '{username}' (id={row['id']}).")
        else:
            print(f"Cleared avatar for '{username}' (id={row['id']}); {filename} was not found in storage.")


def main(argv=None, app=None):
    parser = argparse.ArgumentParser(description="Remove a player's uploaded avatar.")
    parser.add_argument('username')
    args = parser.parse_args(argv)
    remove_avatar(args.username, app=app)


if __name__ == '__main__':
    main()
