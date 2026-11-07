"""Throwaway "demo short" used by the Advanced tutorial.

Several Advanced pages (dashboard summary, finances, portfolio shorts tab,
leaderboard short-equity column, SL/TP controls) show nothing until the player
holds a short. So the tour opens one tiny short (1 unit of the cheapest ore) for
the duration, then removes it, leaving the account exactly as it was.

Glitch-proofing — this must never become a way to gain money on replay:
  * Opening first clears any stale demo short for the user.
  * The position is flagged is_demo=1 so it can be targeted precisely and is
    never mistaken for a real position.
  * Closing refunds the EXACT margin that was deducted at open (ignoring any
    fees the engine accrued meanwhile) and DELETES the row — no P/L, no
    transaction record, no advancement evaluation. Net balance change: zero.
  * Close is idempotent and also run at tour start, so a crash that leaves a
    demo short open is cleaned up next time.
"""

from app.database import get_db
from app.market.shorting import (
    _calculate_short_ratio,
    _calculate_collateral_multiplier,
    _calculate_total_locked_collateral,
    _calculate_player_margin,
)


def _cheapest_ore(db):
    """Return (id, current_price) of the cheapest positively-priced ore, or None."""
    row = db.execute(
        "SELECT id, current_price FROM ores WHERE current_price > 0 "
        "ORDER BY current_price ASC, id ASC LIMIT 1"
    ).fetchone()
    return (row['id'], row['current_price']) if row else None


def clear_demo_short(user_id):
    """Remove any demo short for the user, refunding the exact margin deducted.

    Returns the number of demo positions removed (0 or more). Safe to call when
    none exist. Never touches real (is_demo=0) positions.
    """
    db = get_db()
    rows = db.execute(
        "SELECT id, share_quantity, entry_price, locked_collateral "
        "FROM short_positions WHERE user_id = ? AND is_demo = 1",
        (user_id,),
    ).fetchall()
    for row in rows:
        # margin = locked_collateral - short_value_at_entry  (price-independent, exact)
        short_value_at_entry = row['share_quantity'] * row['entry_price']
        margin = round(row['locked_collateral'] - short_value_at_entry, 2)
        db.execute(
            "UPDATE users SET balance = balance + ? WHERE id = ?",
            (margin, user_id),
        )
        db.execute("DELETE FROM short_positions WHERE id = ?", (row['id'],))
    if rows:
        db.commit()
    return len(rows)


def open_demo_short(user_id):
    """Open a 1-unit demo short on the cheapest ore for the tour.

    Idempotent: if a demo short already exists it is left exactly as-is (no
    clear-and-reopen), so re-entering the shorting step — e.g. by navigating
    backward and forward through the tour, which re-fires the open action —
    never churns, duplicates, or moves the balance. Returns a dict:
      {ok: True, ore_id, created: True}            -> a demo short now exists
      {ok: True, created: False, reason: 'already open'} -> one already existed
      {ok: True, created: False, reason: '...'}    -> could not open; caller
                                                      should fall back to just
                                                      describing the feature
    Never raises for the expected "can't afford it" case.
    """
    db = get_db()

    # Already open from an earlier visit to the shorting step: do nothing. This is
    # the guard that makes back/forward navigation safe (no infinite recreation).
    if has_demo_short(user_id):
        existing = db.execute(
            "SELECT ore_id FROM short_positions WHERE user_id = ? AND is_demo = 1 LIMIT 1",
            (user_id,),
        ).fetchone()
        return {'ok': True, 'created': False, 'reason': 'already open',
                'ore_id': existing['ore_id'] if existing else None}

    cheapest = _cheapest_ore(db)
    if cheapest is None:
        return {'ok': True, 'created': False, 'reason': 'no ore available'}
    ore_id, price = cheapest

    quantity = 1
    short_ratio = _calculate_short_ratio(db, ore_id)
    multiplier = _calculate_collateral_multiplier(short_ratio)
    locked_collateral = _calculate_total_locked_collateral(quantity, price, multiplier)
    margin = _calculate_player_margin(quantity, price, multiplier)

    user = db.execute("SELECT balance FROM users WHERE id = ?", (user_id,)).fetchone()
    if user is None:
        return {'ok': True, 'created': False, 'reason': 'user not found'}
    if user['balance'] < margin:
        # A just-upgraded player with almost no free cash: don't block the tour.
        return {'ok': True, 'created': False, 'reason': 'insufficient free cash'}

    # Sample SL/TP so the portfolio/finances rows show real values during the
    # tour (short SL sits above entry, TP below). Kept well clear of the current
    # price so the engine won't trigger them during the tour's lifetime.
    stop_loss = round(price * 1.5, 2)
    take_profit = round(price * 0.5, 2)

    db.execute(
        "UPDATE users SET balance = balance - ? WHERE id = ?",
        (margin, user_id),
    )
    db.execute(
        """INSERT INTO short_positions
           (user_id, ore_id, share_quantity, entry_price, locked_collateral,
            stop_loss_price, take_profit_price, is_demo)
           VALUES (?, ?, ?, ?, ?, ?, ?, 1)""",
        (user_id, ore_id, quantity, price, locked_collateral, stop_loss, take_profit),
    )
    db.commit()
    return {'ok': True, 'created': True, 'ore_id': ore_id}


def has_demo_short(user_id):
    """True if the user currently holds a demo short."""
    db = get_db()
    row = db.execute(
        "SELECT 1 FROM short_positions WHERE user_id = ? AND is_demo = 1 LIMIT 1",
        (user_id,),
    ).fetchone()
    return row is not None
