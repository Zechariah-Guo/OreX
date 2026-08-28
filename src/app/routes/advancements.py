"""Advancements testing page (developer tool).

A hidden, no-frills testing page with NO navigation links anywhere in the app.
Only accessible by manually typing /advancements in the URL bar.
"""

from flask import Blueprint, render_template, redirect, url_for, request
from flask_login import login_required, current_user

from app.database import get_db
from app.advancements import ADVANCEMENT_KEYS, ADVANCEMENT_METADATA, get_user_advancements

advancements_bp = Blueprint('advancements', __name__)


@advancements_bp.route('/advancements')
@login_required
def advancements_test():
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

    return render_template(
        'pages/advancements_test.html',
        advancements=advancements_data,
        money_theme=money_theme,
        gold_theme=gold_theme,
        bonus_cycle_day=bonus_cycle_day,
        last_bonus_date=last_bonus_date,
    )


@advancements_bp.route('/advancements/reset/<key>', methods=['POST'])
@login_required
def reset_advancement(key):
    """Strip a single advancement from the current player."""
    if key not in ADVANCEMENT_KEYS:
        return redirect(url_for('advancements.advancements_test'))

    db = get_db()
    db.execute(
        "DELETE FROM advancements WHERE user_id = ? AND advancement_key = ?",
        (current_user.id, key)
    )
    db.commit()
    return redirect(url_for('advancements.advancements_test'))


@advancements_bp.route('/advancements/reset-all', methods=['POST'])
@login_required
def reset_all_advancements():
    """Strip all advancements from the current player."""
    db = get_db()
    db.execute(
        "DELETE FROM advancements WHERE user_id = ?",
        (current_user.id,)
    )
    db.commit()
    return redirect(url_for('advancements.advancements_test'))


@advancements_bp.route('/advancements/grant-all', methods=['POST'])
@login_required
def grant_all_advancements():
    """Award all advancements to the current player (for visual testing)."""
    from app.advancements import award_advancement
    db = get_db()
    for key in ADVANCEMENT_KEYS:
        award_advancement(db, current_user.id, key)
    db.commit()
    return redirect(url_for('advancements.advancements_test'))


@advancements_bp.route('/advancements/trigger-money-theme', methods=['POST'])
@login_required
def trigger_money_theme():
    """Set money_theme_unlocked=1 for the current player (visual testing)."""
    db = get_db()
    db.execute(
        "UPDATE users SET money_theme_unlocked = 1 WHERE id = ?",
        (current_user.id,)
    )
    db.commit()
    return redirect(url_for('advancements.advancements_test'))


@advancements_bp.route('/advancements/trigger-gold-theme', methods=['POST'])
@login_required
def trigger_gold_theme():
    """Set gold_theme_unlocked=1 for the current player (visual testing)."""
    db = get_db()
    db.execute(
        "UPDATE users SET gold_theme_unlocked = 1 WHERE id = ?",
        (current_user.id,)
    )
    db.commit()
    return redirect(url_for('advancements.advancements_test'))


@advancements_bp.route('/advancements/reset-themes', methods=['POST'])
@login_required
def reset_themes():
    """Set both theme flags back to 0."""
    db = get_db()
    db.execute(
        "UPDATE users SET money_theme_unlocked = 0, gold_theme_unlocked = 0 WHERE id = ?",
        (current_user.id,)
    )
    db.commit()
    return redirect(url_for('advancements.advancements_test'))


@advancements_bp.route('/advancements/test-toasts', methods=['POST'])
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
    return redirect(url_for('advancements.advancements_test'))


@advancements_bp.route('/advancements/bonus/set-day', methods=['POST'])
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
    return redirect(url_for('advancements.advancements_test'))


@advancements_bp.route('/advancements/bonus/reset', methods=['POST'])
@login_required
def reset_bonus():
    """Reset bonus to day 1, clear last_bonus_collected_date."""
    db = get_db()
    db.execute(
        "UPDATE users SET bonus_cycle_day = 1, last_bonus_collected_date = NULL WHERE id = ?",
        (current_user.id,)
    )
    db.commit()
    return redirect(url_for('advancements.advancements_test'))


@advancements_bp.route('/advancements/bonus/clear-today', methods=['POST'])
@login_required
def clear_bonus_today():
    """Clear last_bonus_collected_date so the bonus becomes available again today."""
    db = get_db()
    db.execute(
        "UPDATE users SET last_bonus_collected_date = NULL WHERE id = ?",
        (current_user.id,)
    )
    db.commit()
    return redirect(url_for('advancements.advancements_test'))


@advancements_bp.route('/advancements/bonus/complete', methods=['POST'])
@login_required
def complete_bonus():
    """Set bonus_cycle_day to 4 (mark cycle as complete)."""
    db = get_db()
    db.execute(
        "UPDATE users SET bonus_cycle_day = 4 WHERE id = ?",
        (current_user.id,)
    )
    db.commit()
    return redirect(url_for('advancements.advancements_test'))
