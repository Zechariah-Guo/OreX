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

    return render_template(
        'pages/advancements_test.html',
        advancements=advancements_data,
        money_theme=money_theme,
        gold_theme=gold_theme,
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


@advancements_bp.route('/notifications/poll')
@login_required
def poll_notifications():
    """Poll for unread notifications and return toast HTML.

    Returns htmx partial with toast markup for each unread notification.
    Marks returned notifications as read so they aren't shown again.
    """
    db = get_db()

    try:
        notifications = db.execute(
            """SELECT id, category, message, action_url
               FROM notifications
               WHERE user_id = ? AND is_read = 0
               ORDER BY created_at DESC
               LIMIT 5""",
            (current_user.id,),
        ).fetchall()
    except Exception:
        # Table may not exist yet — return empty
        return '', 204

    if not notifications:
        return '', 204

    # Mark as read
    ids = [n['id'] for n in notifications]
    placeholders = ','.join('?' * len(ids))
    db.execute(
        f"UPDATE notifications SET is_read = 1 WHERE id IN ({placeholders})",
        ids,
    )
    db.commit()

    return render_template(
        'partials/notification_toasts.html',
        notifications=notifications,
    )
