"""Testing page (developer tool).

A hidden, no-frills testing page with NO navigation links anywhere in the app.
Only accessible by manually typing /testing in the URL bar, and only in
debug mode (every route 404s otherwise, see _dev_page_debug_only).
"""

from flask import Blueprint, abort, current_app, render_template, redirect, url_for, request
from flask_login import login_required, current_user

from app.database import get_db
from app.advancements import ADVANCEMENT_KEYS, ADVANCEMENT_METADATA, get_user_advancements

testing_bp = Blueprint('testing', __name__)


def _dev_tools_enabled():
    """Debug mode, or OREX_ENABLE_TESTING_PAGE=1 (local Docker testing)."""
    return current_app.debug or bool(current_app.config.get('ENABLE_TESTING_PAGE'))


@testing_bp.before_request
def _dev_page_debug_only():
    """The whole dev page (every /testing* route) exists only in debug mode,
    or when OREX_ENABLE_TESTING_PAGE=1 is set for local Docker testing.

    Blueprint-level so new routes added here are gated automatically. Runs
    before login_required, so when disabled even anonymous users get a plain 404.
    """
    if not _dev_tools_enabled():
        abort(404)


@testing_bp.route('/testing')
@login_required
def testing_page():
    """Display all 9 advancements with earned/locked state and dev controls."""
    db = get_db()
    earned = get_user_advancements(db, current_user.id)
    earned_keys = {a['key'] for a in earned}

    # Build display data
    advancements_data = []
    for key in ADVANCEMENT_KEYS:
        meta = ADVANCEMENT_METADATA[key]
        advancements_data.append({
            'key': key,
            'name': meta['name'],
            'description': meta['description'],
            'earned': key in earned_keys,
        })

    # Get theme state
    row = db.execute(
        "SELECT money_theme_unlocked, gold_theme_unlocked FROM users WHERE id = ?",
        (current_user.id,)
    ).fetchone()
    money_theme = bool(row['money_theme_unlocked']) if row else False
    gold_theme = bool(row['gold_theme_unlocked']) if row else False

    # Get bonus state
    bonus_row = db.execute(
        "SELECT bonus_cycle_day, last_bonus_collected_date FROM users WHERE id = ?",
        (current_user.id,)
    ).fetchone()
    bonus_cycle_day = bonus_row['bonus_cycle_day'] if bonus_row else 1
    last_bonus_date = bonus_row['last_bonus_collected_date'] if bonus_row else None

    free_cash = db.execute(
        "SELECT balance FROM users WHERE id = ?", (current_user.id,)
    ).fetchone()['balance']

    return render_template(
        'pages/testing.html',
        advancements=advancements_data,
        money_theme=money_theme,
        gold_theme=gold_theme,
        bonus_cycle_day=bonus_cycle_day,
        last_bonus_date=last_bonus_date,
        free_cash=free_cash,
        cash_tools_enabled=_dev_tools_enabled(),
        cash_grant_amount=DEV_CASH_GRANT,
    )


# --- Free cash dev tools (debug mode only) ---
# These edit a player's money, so unlike the rest of this page they refuse to
# run outside debug mode: a production player typing the URL gets a 404.

DEV_CASH_GRANT = 100_000


def _require_debug():
    if not _dev_tools_enabled():
        abort(404)


@testing_bp.route('/testing/cash/drain', methods=['POST'])
@login_required
def drain_free_cash():
    """Set free cash to $0. With an open short, the next tick fee-liquidates it."""
    _require_debug()
    db = get_db()
    db.execute("UPDATE users SET balance = 0 WHERE id = ?", (current_user.id,))
    db.commit()
    return redirect(url_for('testing.testing_page'))


@testing_bp.route('/testing/cash/grant', methods=['POST'])
@login_required
def grant_free_cash():
    """Add DEV_CASH_GRANT to free cash."""
    _require_debug()
    db = get_db()
    db.execute(
        "UPDATE users SET balance = balance + ? WHERE id = ?",
        (DEV_CASH_GRANT, current_user.id),
    )
    db.commit()
    return redirect(url_for('testing.testing_page'))


@testing_bp.route('/testing/reset/<key>', methods=['POST'])
@login_required
def reset_advancement(key):
    """Strip a single advancement from the current player."""
    if key not in ADVANCEMENT_KEYS:
        return redirect(url_for('testing.testing_page'))

    db = get_db()
    db.execute(
        "DELETE FROM advancements WHERE user_id = ? AND advancement_key = ?",
        (current_user.id, key)
    )
    db.commit()
    return redirect(url_for('testing.testing_page'))


@testing_bp.route('/testing/reset-all', methods=['POST'])
@login_required
def reset_all_advancements():
    """Strip all advancements from the current player."""
    db = get_db()
    db.execute(
        "DELETE FROM advancements WHERE user_id = ?",
        (current_user.id,)
    )
    db.commit()
    return redirect(url_for('testing.testing_page'))


@testing_bp.route('/testing/grant-all', methods=['POST'])
@login_required
def grant_all_advancements():
    """Award all advancements to the current player (for visual testing)."""
    from app.advancements import award_advancement
    db = get_db()
    for key in ADVANCEMENT_KEYS:
        award_advancement(db, current_user.id, key)
    db.commit()
    return redirect(url_for('testing.testing_page'))


@testing_bp.route('/testing/trigger-money-theme', methods=['POST'])
@login_required
def trigger_money_theme():
    """Set money_theme_unlocked=1 for the current player (visual testing)."""
    db = get_db()
    db.execute(
        "UPDATE users SET money_theme_unlocked = 1 WHERE id = ?",
        (current_user.id,)
    )
    db.commit()
    return redirect(url_for('testing.testing_page'))


@testing_bp.route('/testing/trigger-gold-theme', methods=['POST'])
@login_required
def trigger_gold_theme():
    """Set gold_theme_unlocked=1 for the current player (visual testing)."""
    db = get_db()
    db.execute(
        "UPDATE users SET gold_theme_unlocked = 1 WHERE id = ?",
        (current_user.id,)
    )
    db.commit()
    return redirect(url_for('testing.testing_page'))


@testing_bp.route('/testing/reset-themes', methods=['POST'])
@login_required
def reset_themes():
    """Set both theme flags back to 0."""
    db = get_db()
    db.execute(
        "UPDATE users SET money_theme_unlocked = 0, gold_theme_unlocked = 0 WHERE id = ?",
        (current_user.id,)
    )
    db.commit()
    return redirect(url_for('testing.testing_page'))


@testing_bp.route('/testing/test-toasts', methods=['POST'])
@login_required
def test_toasts():
    """Fire one of each toast category for visual testing."""
    from flask import flash
    flash('Success toast — buy/sell confirmation', 'success')
    flash('Error toast — validation failed', 'error')
    flash('Info toast — neutral information', 'info')
    flash('Achievement toast — gold/yellow theme', 'advancement')
    flash('Liquidation toast — red danger theme', 'liquidation')
    flash('Stop Loss toast — red with bell', 'stop-loss')
    flash('Take Profit toast — green with bell', 'take-profit')
    flash('Short open toast — purple theme', 'short-open')
    flash('Short close toast — blue theme', 'short-close')
    flash('Default toast — green (polling fallback)', 'default')
    return redirect(url_for('testing.testing_page'))


@testing_bp.route('/testing/bonus/set-day', methods=['POST'])
@login_required
def set_bonus_day():
    """Set bonus_cycle_day to a specific value for testing."""
    day = int(request.form.get('day', 1))
    if day < 1:
        day = 1
    if day > 4:
        day = 4
    db = get_db()
    db.execute(
        "UPDATE users SET bonus_cycle_day = ? WHERE id = ?",
        (day, current_user.id)
    )
    db.commit()
    return redirect(url_for('testing.testing_page'))


@testing_bp.route('/testing/bonus/reset', methods=['POST'])
@login_required
def reset_bonus():
    """Reset bonus to day 1, clear last_bonus_collected_date."""
    db = get_db()
    db.execute(
        "UPDATE users SET bonus_cycle_day = 1, last_bonus_collected_date = NULL WHERE id = ?",
        (current_user.id,)
    )
    db.commit()
    return redirect(url_for('testing.testing_page'))


@testing_bp.route('/testing/bonus/clear-today', methods=['POST'])
@login_required
def clear_bonus_today():
    """Clear last_bonus_collected_date so the bonus becomes available again today."""
    db = get_db()
    db.execute(
        "UPDATE users SET last_bonus_collected_date = NULL WHERE id = ?",
        (current_user.id,)
    )
    db.commit()
    return redirect(url_for('testing.testing_page'))


@testing_bp.route('/testing/bonus/complete', methods=['POST'])
@login_required
def complete_bonus():
    """Set bonus_cycle_day to 4 (mark cycle as complete)."""
    db = get_db()
    db.execute(
        "UPDATE users SET bonus_cycle_day = 4 WHERE id = ?",
        (current_user.id,)
    )
    db.commit()
    return redirect(url_for('testing.testing_page'))
