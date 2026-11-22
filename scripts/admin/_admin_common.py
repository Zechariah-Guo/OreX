"""Shared setup for the admin scripts (not a script itself).

Importing this module puts src/ on sys.path and allows the public dev secret, the
same two lines drop_user.py and reset_password.py start with. The scripts use the
app's configured database (app.config DATABASE_PATH), so inside the Docker image
that is /app/src/data/orex.db (the orex-data volume).
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))

# Local maintenance script: allow the public dev secret (create_app() otherwise refuses in production mode)
os.environ.setdefault('OREX_ALLOW_DEFAULT_SECRET', '1')

# Bots are rows in users with this password hash (see app.market.bots). They are not players.
BOT_PASSWORD_HASH = 'BOT_NO_LOGIN'


def create_script_app():
    """Build the Flask app without starting the market engine thread.

    create_app() starts the engine unless TESTING is set. An admin script has no
    business ticking the market (or writing prices) next to the live server.
    """
    import app.market.engine as engine
    engine.start_engine = lambda app: None
    from app import create_app
    return create_app()


def find_player(db, username):
    """Return the users row for a real player, or exit 1 with a message."""
    row = db.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
    if not row:
        print(f"User '{username}' not found.")
        sys.exit(1)
    if row['password_hash'] == BOT_PASSWORD_HASH:
        print(f"'{username}' is a bot, not a player.")
        sys.exit(1)
    return row
