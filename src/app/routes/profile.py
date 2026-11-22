"""Profile page: player identity hub with avatar, stats, bonus, and achievements."""

import logging

from flask import (
    Blueprint, abort, current_app, flash, redirect, render_template, request, url_for,
)
from flask_login import login_required, current_user

from app.advancements import (
    get_user_advancements, ADVANCEMENT_KEYS, ADVANCEMENT_METADATA, ADVANCEMENT_IMAGES,
)
from app.avatar import (
    validate_avatar, process_avatar, get_avatar_color_hex, get_avatar_text_color,
)
from app.bonus import (
    is_bonus_available, get_bonus_amount, is_bonus_complete, collect_bonus,
    seconds_until_next_bonus,
)
from app.database import get_db
from app.storage import get_storage_backend

logger = logging.getLogger(__name__)

profile_bp = Blueprint('profile', __name__)

# Bot accounts are created with this placeholder hash (see market/bots.py)
BOT_PASSWORD_HASH = 'BOT_NO_LOGIN'


@profile_bp.route('/profile')
@login_required
def overview():
    """Render the current player's own profile (editable avatar, daily bonus)."""
    return _render_profile(current_user.id, is_own_profile=True)


@profile_bp.route('/player/<username>')
@login_required
def player(username):
    """Read-only public profile of another player, linked from the leaderboard.

    Usernames are case-sensitive in the DB, so an exact match wins. Otherwise a
    case-insensitive match redirects to the canonical URL, but only when it is
    unambiguous. Bots have no profile, and your own name redirects to /profile.
    """
    db = get_db()
    row = db.execute(
        "SELECT id, username, password_hash, suspended_at FROM users WHERE username = ?",
        (username,),
    ).fetchone()

    if row is None:
        matches = db.execute(
            "SELECT id, username, password_hash FROM users WHERE username = ? COLLATE NOCASE",
            (username,),
        ).fetchall()
        if len(matches) != 1:
            abort(404)
        return redirect(url_for('profile.player', username=matches[0]['username']))

    if row['password_hash'] == BOT_PASSWORD_HASH or row['suspended_at']:
        abort(404)

    if row['id'] == current_user.id:
        return redirect(url_for('profile.overview'))

    return _render_profile(row['id'], is_own_profile=False)


def most_recent_unlock_index(achievements):
    """Index of the most recently unlocked achievement, or 0 if none is unlocked.

    The phone carousel opens on this badge. Timestamps have one-second
    resolution, so ties go to the later badge in list order.
    """
    best = 0
    best_stamp = None
    for index, ach in enumerate(achievements):
        stamp = ach['earned_at'] if ach['earned'] else None
        if stamp is None:
            continue
        if best_stamp is None or stamp >= best_stamp:
            best, best_stamp = index, stamp
    return best


def _render_profile(user_id, is_own_profile):
    """Shared renderer for /profile (own) and /player/<username> (others).

    Other players' pages never get the daily bonus or avatar-upload controls.
    """
    db = get_db()

    user = db.execute(
        """SELECT id, username, balance, created_at, avatar_path, avatar_color,
                  bonus_cycle_day, last_bonus_collected_date,
                  play_time, login_streak, peak_net_worth
           FROM users WHERE id = ?""",
        (user_id,),
    ).fetchone()
    if user is None:
        abort(404)

    trade_count = db.execute(
        "SELECT COUNT(*) as cnt FROM transactions WHERE user_id = ?",
        (user_id,),
    ).fetchone()['cnt']

    # Merge earned advancements with full metadata for template display
    earned = get_user_advancements(db, user_id)
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
            'image': ADVANCEMENT_IMAGES.get(key, f'{key}.webp'),
        }
        achievements.append(entry)

    # Fallback avatar colours for THIS profile's owner. Deliberately not the
    # user_avatar_* context values: those belong to the viewer's nav avatar.
    color_key = user['avatar_color'] or 'coal'
    context = {
        'user': user,
        'trade_count': trade_count,
        'achievements': achievements,
        'carousel_start_index': most_recent_unlock_index(achievements),
        'is_own_profile': is_own_profile,
        'profile_avatar_hex': get_avatar_color_hex(color_key),
        'profile_avatar_text': get_avatar_text_color(color_key),
        # The achievement-orbit animation on this page uses Alpine.js directly,
        # independent of the tutorial system, so it must load it unconditionally.
        'needs_alpine': True,
    }

    if is_own_profile:
        context.update(
            bonus_available=is_bonus_available(user),
            bonus_amount=get_bonus_amount(user['bonus_cycle_day']),
            bonus_complete=is_bonus_complete(user['bonus_cycle_day']),
            bonus_seconds_left=seconds_until_next_bonus(),
        )

    return render_template('pages/profile.html', **context)


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
        bonus_seconds_left=seconds_until_next_bonus(),
    )


def _get_current_avatar_url() -> str | None:
    """Resolve the current user's avatar URL for error-state partials.

    Returns None when the user has no uploaded avatar: the default avatar is
    the initials circle, so there is no default image to return.
    """
    db = get_db()
    row = db.execute(
        "SELECT avatar_path FROM users WHERE id = ?",
        (current_user.id,),
    ).fetchone()

    if row and row['avatar_path']:
        filename = f"{current_user.id}.webp"
        storage = get_storage_backend(current_app)
        return storage.get_url(filename)

    return None
