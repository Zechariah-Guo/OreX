"""Suspend a player's account (reversible; see unsuspend_user.py).

A suspended account cannot sign in (it sees "This account has been suspended.
Contact orexsupport@gmail.com."), is signed out everywhere (session_version is
raised), and is hidden from the leaderboard and public profiles. Nothing is
deleted, except the player's push subscriptions and presence rows (they get no
more pushes; they can turn pushes on again after a suspension is lifted). The
player's existing positions stay in the database.

Usage:
    python scripts/admin/suspend_user.py <username>
    python scripts/admin/suspend_user.py <username> --reason "Offensive username"
"""

import argparse
from datetime import datetime

from _admin_common import create_script_app, find_player

from app.models import get_db


def suspend_user(username, reason=None, app=None):
    app = app or create_script_app()
    with app.app_context():
        db = get_db()
        row = find_player(db, username)
        if row['suspended_at']:
            print(f"User '{username}' is already suspended (since {row['suspended_at']}). No change.")
            return
        db.execute(
            "UPDATE users SET suspended_at = ?, suspended_reason = ?, "
            "session_version = session_version + 1 WHERE id = ?",
            (datetime.now().isoformat(timespec='seconds'), reason, row['id']),
        )
        # A suspended player must not keep getting pushes on their devices
        db.execute("DELETE FROM push_subscriptions WHERE user_id = ?", (row['id'],))
        db.execute("DELETE FROM push_presence WHERE user_id = ?", (row['id'],))
        db.commit()
        print(f"Suspended user '{username}' (id={row['id']}). Undo with unsuspend_user.py.")


def main(argv=None, app=None):
    parser = argparse.ArgumentParser(description="Suspend a player's account.")
    parser.add_argument('username')
    parser.add_argument('--reason', help="internal note kept with the suspension (not shown in the app; included in the player's data export)")
    args = parser.parse_args(argv)
    suspend_user(args.username, args.reason, app=app)


if __name__ == '__main__':
    main()
