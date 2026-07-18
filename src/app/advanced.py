"""Advanced Mode core utility functions.

Handles eligibility detection, purchase, toggle, and status queries
for the OreX Advanced Mode prestige layer.
"""

from datetime import datetime

from flask import current_app

from app.database import get_db


def check_eligibility(user_id: int) -> bool:
    """Check if a user is eligible for Advanced Mode.

    A user becomes eligible once their net worth (balance + holdings market value)
    reaches the threshold ($100,000). Eligibility is sticky — once set, it never
    reverts (except on account reset).

    Returns True if the user is eligible (either newly or previously).
    """
    db = get_db()

    user = db.execute(
        "SELECT balance, advanced_eligible FROM users WHERE id = ?",
        (user_id,)
    ).fetchone()

    if user is None:
        return False

    # If already marked eligible, return True immediately (sticky)
    if user['advanced_eligible'] == 1:
        return True

    # Calculate net worth: balance + SUM(holdings.quantity * ores.current_price)
    holdings_value_row = db.execute(
        """SELECT COALESCE(SUM(h.quantity * o.current_price), 0) as holdings_value
           FROM holdings h
           JOIN ores o ON h.ore_id = o.id
           WHERE h.user_id = ?""",
        (user_id,)
    ).fetchone()

    net_worth = user['balance'] + holdings_value_row['holdings_value']
    threshold = current_app.config['ADVANCED_MODE_THRESHOLD']

    if net_worth >= threshold:
        # Mark as permanently eligible
        db.execute(
            "UPDATE users SET advanced_eligible = 1 WHERE id = ?",
            (user_id,)
        )
        db.commit()
        return True

    return False


def purchase_advanced_mode(user_id: int) -> tuple:
    """Purchase Advanced Mode for the user.

    Validates:
    - User must be eligible (advanced_eligible = 1)
    - User must have sufficient free cash (balance >= $50,000)
    - User must not have already purchased

    Returns (success: bool, message: str).
    """
    db = get_db()

    user = db.execute(
        "SELECT balance, advanced_eligible, advanced_purchased FROM users WHERE id = ?",
        (user_id,)
    ).fetchone()

    if user is None:
        return (False, "User not found.")

    # Already purchased — no-op
    if user['advanced_purchased'] == 1:
        return (False, "You already own Advanced Mode.")

    # Must be eligible
    if user['advanced_eligible'] != 1:
        return (False, "You must reach $100,000 net worth before purchasing Advanced Mode.")

    cost = current_app.config['ADVANCED_MODE_COST']

    # Must have sufficient funds
    if user['balance'] < cost:
        return (False, "Insufficient funds. You need $50,000 free cash to purchase Advanced Mode.")

    # Deduct cost and set purchased flag (atomic)
    new_balance = user['balance'] - cost
    db.execute(
        "UPDATE users SET balance = ?, advanced_purchased = 1 WHERE id = ?",
        (new_balance, user_id)
    )
    db.commit()

    return (True, "Advanced Mode purchased successfully!")


def toggle_advanced_mode(user_id: int) -> tuple:
    """Toggle Advanced Mode on or off for the user.

    Validates:
    - User must have purchased Advanced Mode
    - Must respect 5-minute cooldown from last toggle

    Returns (success: bool, message: str).
    """
    db = get_db()

    user = db.execute(
        "SELECT advanced_purchased, advanced_active, advanced_toggled_at FROM users WHERE id = ?",
        (user_id,)
    ).fetchone()

    if user is None:
        return (False, "User not found.")

    if user['advanced_purchased'] != 1:
        return (False, "You must purchase Advanced Mode before toggling.")

    cooldown = current_app.config['ADVANCED_TOGGLE_COOLDOWN']
    now = datetime.now()

    # Check cooldown
    if user['advanced_toggled_at'] is not None:
        last_toggle = datetime.fromisoformat(user['advanced_toggled_at'])
        elapsed = (now - last_toggle).total_seconds()
        if elapsed < cooldown:
            remaining = int(cooldown - elapsed)
            minutes = remaining // 60
            seconds = remaining % 60
            return (False, f"Please wait {minutes} minutes {seconds} seconds before toggling again.")

    # Flip the active state
    new_active = 0 if user['advanced_active'] == 1 else 1

    # Block disabling if user has active short positions
    if new_active == 0:
        active_shorts = db.execute(
            "SELECT COUNT(*) as cnt FROM short_positions WHERE user_id = ? AND status = 'active'",
            (user_id,)
        ).fetchone()
        if active_shorts['cnt'] > 0:
            return (False, "You have active short positions. Close all shorts before disabling Advanced Mode.")

    now_iso = now.isoformat()

    db.execute(
        "UPDATE users SET advanced_active = ?, advanced_toggled_at = ? WHERE id = ?",
        (new_active, now_iso, user_id)
    )
    db.commit()

    state_label = "enabled" if new_active == 1 else "disabled"
    return (True, f"Advanced Mode {state_label}.")


def is_advanced_active(user_id: int) -> bool:
    """Return True if the user has Advanced Mode purchased AND currently active."""
    db = get_db()

    row = db.execute(
        "SELECT advanced_purchased, advanced_active FROM users WHERE id = ?",
        (user_id,)
    ).fetchone()

    if row is None:
        return False

    return row['advanced_purchased'] == 1 and row['advanced_active'] == 1


def get_advanced_status(user_id: int) -> dict:
    """Return full Advanced Mode status for a user.

    Returns dict with:
    - eligible (bool): whether the user is eligible to purchase
    - purchased (bool): whether the user has purchased Advanced Mode
    - active (bool): whether Advanced Mode is currently active
    - cooldown_remaining (int): seconds remaining on toggle cooldown (0 if no cooldown)
    """
    db = get_db()

    user = db.execute(
        "SELECT advanced_eligible, advanced_purchased, advanced_active, advanced_toggled_at FROM users WHERE id = ?",
        (user_id,)
    ).fetchone()

    if user is None:
        return {
            'eligible': False,
            'purchased': False,
            'active': False,
            'cooldown_remaining': 0,
        }

    # Actively check eligibility if not already flagged
    eligible = bool(user['advanced_eligible'])
    if not eligible:
        eligible = check_eligibility(user_id)

    cooldown_remaining = 0
    if user['advanced_toggled_at'] is not None:
        cooldown = current_app.config['ADVANCED_TOGGLE_COOLDOWN']
        last_toggle = datetime.fromisoformat(user['advanced_toggled_at'])
        elapsed = (datetime.now() - last_toggle).total_seconds()
        if elapsed < cooldown:
            cooldown_remaining = int(cooldown - elapsed)

    return {
        'eligible': eligible,
        'purchased': bool(user['advanced_purchased']),
        'active': bool(user['advanced_purchased'] and user['advanced_active']),
        'cooldown_remaining': cooldown_remaining,
    }
