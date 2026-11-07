"""Profile page: player identity hub with avatar, stats, bonus, and achievements."""

import logging

from flask import Blueprint, current_app, flash, render_template, request, url_for
from flask_login import login_required, current_user

from app.advancements import get_user_advancements, ADVANCEMENT_KEYS, ADVANCEMENT_METADATA
from app.avatar import validate_avatar, process_avatar
from app.bonus import is_bonus_available, get_bonus_amount, is_bonus_complete, collect_bonus
from app.database import get_db
from app.storage import get_storage_backend

logger = logging.getLogger(__name__)

profile_bp = Blueprint('profile', __name__)


@profile_bp.route('/profile')
@login_required
def overview():
    """Render the profile page with avatar, stats, bonus, and achievements."""
    db = get_db()

    user = db.execute(
        """SELECT username, balance, created_at, avatar_path,
                  bonus_cycle_day, last_bonus_collected_date,
                  play_time, login_streak, peak_net_worth
           FROM users WHERE id = ?""",
        (current_user.id,),
    ).fetchone()

    trade_count = db.execute(
        "SELECT COUNT(*) as cnt FROM transactions WHERE user_id = ?",
        (current_user.id,),
    ).fetchone()['cnt']

    # Image filename mapping (keys -> actual filenames in static/images/advancements/)
    ADVANCEMENT_IMAGES = {
        'millionaire': 'Millionaire.png',
        'multimillionaire': 'Multimillionaire.png',
        'the_big_short': 'The Big Short.png',
        'dedicated': 'Dedicated.png',
        'day_trader': 'What a Deal!.png',
        'budding_enthusiast': 'Suit Up.png',
        'completionist': 'Completionist.png',
        'tragedy': 'Post Mortem.png',
        'best_of_the_rest': 'Go for Diamond!.png',
    }

    # Merge earned advancements with full metadata for template display
    earned = get_user_advancements(db, current_user.id)
    earned_keys = {a['key'] for a in earned}
    achievements = []
    for key in ADVANCEMENT_KEYS:
        meta = ADVANCEMENT_METADATA[key]
        entry = {
            'key': key,
            'name': meta['name'],
            'description': meta['description'],
            'earned': key in earned_keys,
            'earned_at': next(
                (a['earned_at'] for a in earned if a['key'] == key), None
            ),
            'image': ADVANCEMENT_IMAGES.get(key, f'{key}.png'),
        }
        achievements.append(entry)

    bonus_available = is_bonus_available(user)
    bonus_amount = get_bonus_amount(user['bonus_cycle_day'])
    bonus_complete = is_bonus_complete(user['bonus_cycle_day'])

    return render_template(
        'pages/profile.html',
        user=user,
        trade_count=trade_count,
        achievements=achievements,
        bonus_available=bonus_available,
        bonus_amount=bonus_amount,
        bonus_complete=bonus_complete,
        # The achievement-orbit animation on this page uses Alpine.js directly,
        # independent of the tutorial system, so it must load it unconditionally.
        needs_alpine=True,
    )


@profile_bp.route('/profile/avatar', methods=['POST'])
@login_required
def upload_avatar():
    """Handle PFP upload: validate, resize, store, update DB.

    Expects a multipart/form-data POST with an 'avatar' file field.
    Returns an htmx partial with the new avatar image tag for in-place swap.
    """
    # Check file presence
    if 'avatar' not in request.files:
        flash('No file selected.', 'error')
        return render_template('partials/profile_avatar.html',
                               avatar_url=_get_current_avatar_url()), 400

    file = request.files['avatar']
    if file.filename == '':
        flash('No file selected.', 'error')
        return render_template('partials/profile_avatar.html',
                               avatar_url=_get_current_avatar_url()), 400

    # Read file data
    file_data = file.read()

    # Validate (checks size and format)
    is_valid, error_message = validate_avatar(file_data)
    if not is_valid:
        flash(error_message, 'error')
        return render_template('partials/profile_avatar.html',
                               avatar_url=_get_current_avatar_url()), 400

    # Process: resize to 300x300 WebP
    processed_data = process_avatar(file_data)

    # Store with filename derived from user_id
    filename = f"{current_user.id}.webp"
    storage = get_storage_backend(current_app)

    try:
        stored_path = storage.store(filename, processed_data, 'image/webp')
    except Exception:
        logger.exception("Failed to store avatar for user %s", current_user.id)
        flash('Failed to save avatar. Please try again.', 'error')
        return render_template('partials/profile_avatar.html',
                               avatar_url=_get_current_avatar_url()), 500

    # Update avatar_path in the database
    db = get_db()
    db.execute(
        "UPDATE users SET avatar_path = ? WHERE id = ?",
        (stored_path, current_user.id),
    )
    db.commit()

    # Return htmx partial with updated avatar
    avatar_url = storage.get_url(filename)
    return render_template('partials/profile_avatar.html', avatar_url=avatar_url)


@profile_bp.route('/profile/bonus/collect', methods=['POST'])
@login_required
def collect_bonus_route():
    """Collect the daily login bonus if eligible.

    Returns an htmx partial with updated bonus section state.
    """
    db = get_db()
    success, amount = collect_bonus(db, current_user.id)

    if success:
        # Refresh current_user balance so OOB nav swap shows updated value
        updated_user = db.execute(
            "SELECT balance FROM users WHERE id = ?", (current_user.id,)
        ).fetchone()
        current_user.balance = updated_user['balance']
        flash(f"Collected ${amount:,} bonus!", 'success')
    else:
        # Determine reason for failure
        user = db.execute(
            "SELECT bonus_cycle_day, last_bonus_collected_date FROM users WHERE id = ?",
            (current_user.id,),
        ).fetchone()

        if is_bonus_complete(user['bonus_cycle_day']):
            flash("Bonus cycle already completed.", 'error')
        else:
            flash("Already collected today. Come back tomorrow!", 'info')

    # Re-query user state after potential update
    user = db.execute(
        """SELECT username, bonus_cycle_day, last_bonus_collected_date
           FROM users WHERE id = ?""",
        (current_user.id,),
    ).fetchone()

    bonus_available = is_bonus_available(user)
    bonus_amount = get_bonus_amount(user['bonus_cycle_day'])
    bonus_complete = is_bonus_complete(user['bonus_cycle_day'])

    return render_template(
        'partials/profile_bonus.html',
        user=user,
        bonus_available=bonus_available,
        bonus_amount=bonus_amount,
        bonus_complete=bonus_complete,
    )


def _get_current_avatar_url() -> str:
    """Resolve the current user's avatar URL for error-state partials."""
    db = get_db()
    row = db.execute(
        "SELECT avatar_path FROM users WHERE id = ?",
        (current_user.id,),
    ).fetchone()

    if row and row['avatar_path']:
        filename = f"{current_user.id}.webp"
        storage = get_storage_backend(current_app)
        return storage.get_url(filename)

    return url_for('static', filename='images/default-avatar.png')
