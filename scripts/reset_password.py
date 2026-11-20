"""Reset a user's password by username without needing to log in.

Use this when a user forgot their password and has no recovery key.
Two-factor authentication and the recovery key are left untouched.

Usage:
    python scripts/reset_password.py <username>             (prompts for the new password twice)
    python scripts/reset_password.py <username> --random    (generates and prints a temporary password)
"""

import sys
import os
import getpass
import secrets
import string

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

# Local maintenance script: allow the public dev secret (create_app() otherwise refuses in production mode)
os.environ.setdefault('OREX_ALLOW_DEFAULT_SECRET', '1')

from app import create_app
from app.models import get_db, update_password
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


def reset_password(username, new_password, app=None):
    app = app or create_app()
    with app.app_context():
        db = get_db()
        row = db.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone()
        if not row:
            print(f"User '{username}' not found.")
            sys.exit(1)
        update_password(row['id'], new_password)
        print(f"Password reset for user '{username}' (id={row['id']}).")


def main(argv):
    if len(argv) < 2 or argv[1].startswith('--') or len(argv) > 3 or (len(argv) == 3 and argv[2] != '--random'):
        print("Usage: python scripts/reset_password.py <username> [--random]")
        sys.exit(1)

    username = argv[1]

    if len(argv) == 3:
        new_password = generate_temp_password()
        reset_password(username, new_password)
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
    reset_password(username, new_password)


if __name__ == '__main__':
    main(sys.argv)
