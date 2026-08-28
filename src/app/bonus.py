from datetime import date

BONUS_AMOUNTS = {1: 1000, 2: 10000, 3: 100000}


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
