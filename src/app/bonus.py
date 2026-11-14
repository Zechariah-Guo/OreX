from datetime import date, datetime, time, timedelta

from app.config import Config

# Single source of truth lives in config.py; re-exported here so existing
# imports of BONUS_AMOUNTS from app.bonus keep working.
BONUS_AMOUNTS = Config.BONUS_AMOUNTS


def is_bonus_available(user_row) -> bool:
    """Check if the player can collect a bonus today.
    Returns True if bonus_cycle_day < 4 AND last_bonus_collected_date != today.
    """
    cycle_day = user_row['bonus_cycle_day']
    last_collected = user_row['last_bonus_collected_date']

    if cycle_day >= 4:
        return False

    if last_collected is None:
        return True

    return last_collected != date.today().isoformat()


def seconds_until_next_bonus() -> int:
    """Seconds until the next server-local midnight, when the next bonus unlocks.

    Includes a 1s buffer so a client reloading at zero never lands just before
    the date rolls over.
    """
    now = datetime.now()
    midnight = datetime.combine(now.date() + timedelta(days=1), time.min)
    return int((midnight - now).total_seconds()) + 1


def ensure_bonus_reminder(db, user_id: int) -> None:
    """Create today's daily-bonus reminder notification if one is due.

    Does nothing unless a bonus is available and no 'bonus' notification has
    been created yet today. Called from the inbox poll, so it covers both the
    first page load after login and a tab left open past midnight.
    """
    user = db.execute(
        "SELECT bonus_cycle_day, last_bonus_collected_date FROM users WHERE id = ?",
        (user_id,)
    ).fetchone()
    if user is None or not is_bonus_available(user):
        return

    already = db.execute(
        """SELECT 1 FROM notifications
           WHERE user_id = ? AND category = 'bonus'
             AND date(created_at) = date('now', 'localtime')
           LIMIT 1""",
        (user_id,)
    ).fetchone()
    if already:
        return

    # Imported here to avoid a circular import (models -> ... -> bonus)
    from app.models import create_notification
    amount = get_bonus_amount(user['bonus_cycle_day'])
    create_notification(
        user_id, 'bonus',
        f"Your daily bonus of ${amount:,} is ready to collect.",
        target_url='/profile',
    )


def get_bonus_amount(cycle_day: int) -> int:
    """Get the reward amount for the given cycle day. Returns 0 if cycle is complete."""
    return BONUS_AMOUNTS.get(cycle_day, 0)


def is_bonus_complete(cycle_day: int) -> bool:
    """Check if the entire bonus cycle is permanently complete."""
    return cycle_day >= 4


def collect_bonus(db, user_id: int) -> tuple[bool, int]:
    """Attempt to collect the daily bonus.
    Returns (success, amount_awarded).
    """
    today = date.today().isoformat()
    row = db.execute(
        "SELECT bonus_cycle_day, last_bonus_collected_date FROM users WHERE id = ?",
        (user_id,)
    ).fetchone()

    cycle_day = row['bonus_cycle_day']
    last_collected = row['last_bonus_collected_date']

    # Guard: cycle already complete
    if cycle_day >= 4:
        return False, 0

    # Guard: already collected today
    if last_collected == today:
        return False, 0

    amount = BONUS_AMOUNTS[cycle_day]
    new_cycle_day = cycle_day + 1

    db.execute(
        """UPDATE users
           SET balance = balance + ?,
               bonus_cycle_day = ?,
               last_bonus_collected_date = ?
           WHERE id = ?""",
        (amount, new_cycle_day, today, user_id)
    )
    db.commit()

    return True, amount
