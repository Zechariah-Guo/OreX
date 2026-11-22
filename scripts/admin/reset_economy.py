"""Reset the whole game economy (for example at the start of a season).

Every real player gets exactly what Settings > Reset Account gives them (it calls
the same reset_account function): starting balance, holdings, stop loss / take
profit orders and short positions cleared, inbox, push subscriptions and tutorial
progress cleared, Advanced Mode state and daily bonus cycle reset, trade history
archived. Every player is signed out (reset_account raises session_version).

Also: ore prices go back to base_price with a fresh trend log, price history is
cleared, and each bot is returned to what a new database has (starting balance, no
holdings, no shorts, no trades).

Kept, as with a player's own reset: accounts, usernames, passwords, 2FA, backup
codes, recovery keys, avatars, achievements, play time, login streak, unlocked
themes, peak net worth, join date, suspensions.

Stop the app first (or accept that the running market engine keeps a little state
in memory), and take a database backup. This cannot be undone.

Usage:
    python scripts/admin/reset_economy.py --dry-run     (print counts, change nothing)
    python scripts/admin/reset_economy.py               (asks you to type RESET)
    python scripts/admin/reset_economy.py --yes         (no prompt, for docker compose exec without -it)
"""

import argparse
import sys

from _admin_common import create_script_app

from app.market.bots import get_bot_user_ids
from app.models import get_db, reset_account

FRESH_TREND_LOG = '["hold","hold","hold","hold","hold"]'  # same as the ores column default


def _count(db, sql, params=()):
    return db.execute(sql, params).fetchone()[0]


def economy_counts(db):
    """Counts of what a reset touches."""
    bot_ids = get_bot_user_ids(db)
    return {
        'players': _count(db, "SELECT COUNT(*) FROM users") - len(bot_ids),
        'bots': len(bot_ids),
        'holdings': _count(db, "SELECT COUNT(*) FROM holdings"),
        'active_shorts': _count(db, "SELECT COUNT(*) FROM short_positions WHERE status = 'active'"),
        'transactions_to_archive': _count(db, "SELECT COUNT(*) FROM transactions WHERE archived = 0"),
        'notifications': _count(db, "SELECT COUNT(*) FROM notifications"),
        'push_subscriptions': _count(db, "SELECT COUNT(*) FROM push_subscriptions"),
        'ores_to_reset': _count(db, "SELECT COUNT(*) FROM ores"),
        'price_history_rows': _count(db, "SELECT COUNT(*) FROM price_history"),
    }


def reset_economy(app=None, dry_run=False, confirm=None):
    """Reset everything. ``confirm`` is a callable returning the typed text (None = no prompt)."""
    app = app or create_script_app()
    with app.app_context():
        db = get_db()
        counts = economy_counts(db)
        print("Economy reset" + (" (dry run, nothing will change)" if dry_run else ""))
        for name, value in counts.items():
            print(f"  {name}: {value}")
        if dry_run:
            return counts

        if confirm is not None and confirm() != 'RESET':
            print("Confirmation did not match 'RESET'. Nothing was changed.")
            sys.exit(1)

        bot_ids = get_bot_user_ids(db)
        player_ids = [r['id'] for r in db.execute("SELECT id FROM users ORDER BY id")
                      if r['id'] not in set(bot_ids)]

        # Same reset as Settings > Reset Account, for every player and bot.
        for user_id in player_ids + bot_ids:
            reset_account(user_id)

        # Bots start like a new database: no trade history at all.
        for bot_id in bot_ids:
            db.execute("DELETE FROM transactions WHERE user_id = ?", (bot_id,))

        db.execute("UPDATE ores SET current_price = base_price, trend_log = ?", (FRESH_TREND_LOG,))
        db.execute("DELETE FROM price_history")
        db.commit()
        print(f"Reset {len(player_ids)} players, {len(bot_ids)} bots and {counts['ores_to_reset']} ores.")
        return counts


def main(argv=None, app=None, input_fn=input):
    parser = argparse.ArgumentParser(description="Reset the whole game economy.")
    parser.add_argument('--dry-run', action='store_true', help="print counts and change nothing")
    parser.add_argument('--yes', action='store_true', help="skip the typed confirmation")
    args = parser.parse_args(argv)
    confirm = None if args.yes else (lambda: input_fn("Type RESET to reset every player, bot and ore price: "))
    reset_economy(app=app, dry_run=args.dry_run, confirm=confirm)


if __name__ == '__main__':
    main()
