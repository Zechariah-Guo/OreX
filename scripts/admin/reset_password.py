"""Reset a user's password by username without needing to log in.

Use this when a user forgot their password and has no recovery key.
Two-factor authentication and the recovery key are left untouched, unless you
add --disable-2fa (for a player who lost both their device and their backup
codes): that also turns two-factor authentication off, removing the secret and
backup codes exactly as Settings does. The player can turn it on again in Settings.

Usage:
    python scripts/admin/reset_password.py <username>                 (prompts for the new password twice)
    python scripts/admin/reset_password.py <username> --random        (generates and prints a temporary password)
    python scripts/admin/reset_password.py <username> --disable-2fa   (also turns off two-factor authentication)
"""

import argparse
import sys
import os
import getpass
import secrets
import string

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))

# Local maintenance script: allow the public dev secret (create_app() otherwise refuses in production mode)
os.environ.setdefault('OREX_ALLOW_DEFAULT_SECRET', '1')

from app import create_app
from app.models import disable_2fa, get_db, update_password
from app.utils.validation import validate_password


def generate_temp_password():
    """Return a random 16-character password that satisfies validate_password."""
    symbols = '!@#$%^&*-_=+'
    pools = [string.ascii_lowercase, string.ascii_uppercase, string.digits, symbols]
    chars = [secrets.choice(pool) for pool in pools]
    everything = ''.join(pools)
    chars += [secrets.choice(everything) for _ in range(12)]
    secrets.SystemRandom().shuffle(chars)
    return ''.join(chars)


def reset_password(username, new_password, app=None, turn_off_2fa=False):
    app = app or create_app()
    with app.app_context():
        db = get_db()
        row = db.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone()
        if not row:
            print(f"User '{username}' not found.")
            sys.exit(1)
        update_password(row['id'], new_password)
        print(f"Password reset for user '{username}' (id={row['id']}).")
        if turn_off_2fa:
            disable_2fa(row['id'])
            print("Two-factor authentication was turned off. The player can turn it on again in Settings.")


def main(argv):
    parser = argparse.ArgumentParser(
        prog='reset_password.py',
        description="Reset a player's password. 2FA and the recovery key are left untouched unless --disable-2fa is given.",
    )
    parser.add_argument('username')
    parser.add_argument('--random', action='store_true',
                        help='generate and print a temporary password instead of prompting')
    parser.add_argument('--disable-2fa', action='store_true', dest='disable_2fa',
                        help='also turn off two-factor authentication (removes the secret and backup codes); '
                             'the player can turn it on again in Settings')
    args = parser.parse_args(argv[1:])
    username = args.username

    if args.random:
        new_password = generate_temp_password()
        reset_password(username, new_password, turn_off_2fa=args.disable_2fa)
        print(f"Temporary password: {new_password}")
        return

    new_password = getpass.getpass("New password: ")
    valid, error = validate_password(new_password)
    if not valid:
        print(error)
        sys.exit(1)
    if getpass.getpass("Confirm new password: ") != new_password:
        print("Passwords do not match.")
        sys.exit(1)
    reset_password(username, new_password, turn_off_2fa=args.disable_2fa)


if __name__ == '__main__':
    main(sys.argv)
