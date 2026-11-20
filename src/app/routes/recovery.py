"""Account recovery routes: forgot password via a one-time recovery key.

Flow:
1. /forgot-password  - username + recovery key. Failures share the login rate
   limiter (``app.routes.auth``) and always return the same generic message.
2. /reset-password   - new password (twice), only reachable through a short-lived
   (5 minute) session holding the verified user id.
3. /recovery-key     - shows a freshly generated key exactly once. The reset
   consumes the old key and issues a new one; registration (when the user ticked
   the box) uses the same page.

The plain recovery key is never stored. It is generated when the flow starts
(its hash is stored then) and only lives in the session until the key page is
first rendered, then it is removed. GET /recovery-key never generates or stores
anything: after the first render it shows an "already shown" state, from which
the user can POST to regenerate (replaces the hash) or continue.
"""

import time

from flask import (
    Blueprint, render_template, redirect, url_for, flash, request, session,
    make_response
)
from flask_login import current_user

from app.models import (
    get_user_by_id,
    get_user_by_username,
    set_recovery_key_hash,
    get_recovery_key_hash,
    reset_password_with_recovery_key,
)
from app.totp import (
    generate_recovery_key,
    hash_recovery_key,
    verify_recovery_key,
)
from app.utils.validation import validate_password

# Reuse the existing shared login rate limiter (same per-IP counter).
from app.routes.auth import (
    _is_rate_limited,
    _record_attempt,
    _rate_limit_retry_minutes,
)
from werkzeug.security import generate_password_hash

recovery_bp = Blueprint('recovery', __name__)

# Pending password-reset session (verified recovery key, new password not yet set).
PENDING_RESET_USER_KEY = 'pending_reset_user_id'
PENDING_RESET_TIME_KEY = 'pending_reset_time'
PENDING_RESET_KEYHASH_KEY = 'pending_reset_key_hash'
PENDING_RESET_TTL = 300  # 5 minutes, same as the pending 2FA session

# One-time key display state.
KEY_USER_KEY = 'recovery_key_user_id'
KEY_PLAIN_KEY = 'recovery_key_plain'
KEY_NEXT_KEY = 'recovery_key_next'
KEY_TIME_KEY = 'recovery_key_time'
KEY_FLOW_TTL = 600  # 10 minutes to view and confirm the key

GENERIC_ERROR = 'Invalid username or recovery key.'

# Dummy hash so unknown users / users without a key cost the same as a real check.
_DUMMY_RECOVERY_HASH = generate_password_hash('dummy-recovery-key-for-timing-safety')


# ---------------------------------------------------------------------------
# Pending reset session
# ---------------------------------------------------------------------------

def _clear_pending_reset():
    session.pop(PENDING_RESET_USER_KEY, None)
    session.pop(PENDING_RESET_TIME_KEY, None)
    session.pop(PENDING_RESET_KEYHASH_KEY, None)


def _get_pending_reset_user_id():
    """Return the verified user id if the reset session is valid, else None."""
    user_id = session.get(PENDING_RESET_USER_KEY)
    created_at = session.get(PENDING_RESET_TIME_KEY)

    if user_id is None or created_at is None:
        return None

    if time.time() - created_at >= PENDING_RESET_TTL:
        _clear_pending_reset()
        return None

    return user_id


# ---------------------------------------------------------------------------
# One-time key display state
# ---------------------------------------------------------------------------

def start_key_display(user_id, plain_key, next_step):
    """Remember a freshly generated key so /recovery-key can show it once.

    ``next_step`` is 'dashboard' (after registration) or 'login' (after a reset).
    """
    session[KEY_USER_KEY] = user_id
    session[KEY_PLAIN_KEY] = plain_key
    session[KEY_NEXT_KEY] = next_step
    session[KEY_TIME_KEY] = time.time()


def _clear_key_display():
    for key in (KEY_USER_KEY, KEY_PLAIN_KEY, KEY_NEXT_KEY, KEY_TIME_KEY):
        session.pop(key, None)


def _get_key_flow():
    """Return (user_id, next_step) for a valid key-display flow, else None."""
    user_id = session.get(KEY_USER_KEY)
    next_step = session.get(KEY_NEXT_KEY)
    created_at = session.get(KEY_TIME_KEY)

    if user_id is None or next_step not in ('dashboard', 'login') or created_at is None:
        _clear_key_display()
        return None

    if time.time() - created_at >= KEY_FLOW_TTL:
        _clear_key_display()
        return None

    # After registration the user is logged in as the key's owner.
    if next_step == 'dashboard' and (
        not current_user.is_authenticated or current_user.id != user_id
    ):
        _clear_key_display()
        return None

    return user_id, next_step


# ---------------------------------------------------------------------------
# Forgot password
# ---------------------------------------------------------------------------

@recovery_bp.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard.overview'))

    if request.method == 'GET':
        return render_template('pages/forgot_password.html')

    ip = request.remote_addr

    if _is_rate_limited(ip):
        minutes = _rate_limit_retry_minutes(ip)
        return render_template(
            'pages/forgot_password.html',
            login_error=f'Too many attempts. Please try again in {minutes} minutes.',
        )

    username = request.form.get('username', '').strip()
    key = request.form.get('recovery_key', '')

    row = get_user_by_username(username) if username else None
    stored_hash = get_recovery_key_hash(row['id']) if row else None

    # Always perform exactly one hash check so timing does not reveal whether
    # the user exists or has a recovery key.
    key_ok = verify_recovery_key(stored_hash or _DUMMY_RECOVERY_HASH, key)

    if not (row and stored_hash and key_ok):
        _record_attempt(ip)
        return render_template(
            'pages/forgot_password.html',
            username=username,
            login_error=GENERIC_ERROR,
        )

    session[PENDING_RESET_USER_KEY] = row['id']
    session[PENDING_RESET_KEYHASH_KEY] = stored_hash  # the exact key that was verified
    session[PENDING_RESET_TIME_KEY] = time.time()
    return redirect(url_for('recovery.reset_password'))


# ---------------------------------------------------------------------------
# Reset password
# ---------------------------------------------------------------------------

@recovery_bp.route('/reset-password', methods=['GET', 'POST'])
def reset_password():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard.overview'))

    user_id = _get_pending_reset_user_id()
    if user_id is None:
        flash('Your password reset session has expired. Please start again.', 'error')
        return redirect(url_for('recovery.forgot_password'))

    if request.method == 'GET':
        return render_template('pages/reset_password.html')

    password = request.form.get('password', '')
    confirm_password = request.form.get('confirm_password', '')

    valid, error = validate_password(password)
    if not valid:
        return render_template('pages/reset_password.html', password_error=error)

    if password != confirm_password:
        return render_template(
            'pages/reset_password.html',
            confirm_error='Passwords do not match.',
        )

    if get_user_by_id(user_id) is None:
        _clear_pending_reset()
        flash('Your password reset session has expired. Please start again.', 'error')
        return redirect(url_for('recovery.forgot_password'))

    # One transaction: consume the old key (single use, checked by row count),
    # set the password, store the new key hash, add the notification. If the key
    # was already used (another tab) nothing changes. The plain key only enters
    # the session after the commit.
    old_key_hash = session.get(PENDING_RESET_KEYHASH_KEY)
    new_key = generate_recovery_key()
    if not old_key_hash or not reset_password_with_recovery_key(
        user_id, old_key_hash, generate_password_hash(password), hash_recovery_key(new_key)
    ):
        _clear_pending_reset()
        flash('Your password reset session has expired. Please start again.', 'error')
        return redirect(url_for('recovery.forgot_password'))

    _clear_pending_reset()
    start_key_display(user_id, new_key, 'login')
    return redirect(url_for('recovery.show_key'))


# ---------------------------------------------------------------------------
# One-time key page
# ---------------------------------------------------------------------------

def _no_flow_redirect():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard.overview'))
    return redirect(url_for('auth.login'))


def _finish_key_flow(next_step):
    _clear_key_display()

    if next_step == 'dashboard':
        flash('Account created successfully. Welcome to OreX!', 'success')
        return redirect(url_for('dashboard.overview'))

    flash('Your password has been reset. Please log in with your new password.', 'success')
    return redirect(url_for('auth.login'))


@recovery_bp.route('/recovery-key', methods=['GET'])
def show_key():
    """Show the key once. Never generates or stores anything (safe for GET)."""
    if _get_key_flow() is None:
        return _no_flow_redirect()

    plain_key = session.pop(KEY_PLAIN_KEY, None)

    response = make_response(render_template(
        'pages/recovery_key.html',
        recovery_key=plain_key,
        already_shown=plain_key is None,
    ))
    response.headers['Cache-Control'] = 'no-store'
    return response


@recovery_bp.route('/recovery-key/regenerate', methods=['POST'])
def regenerate_key():
    """Explicit action: replace the stored hash with a new key, shown once."""
    flow = _get_key_flow()
    if flow is None:
        return _no_flow_redirect()

    user_id, _next_step = flow

    new_key = generate_recovery_key()
    set_recovery_key_hash(user_id, hash_recovery_key(new_key))

    # Refresh the display window and hand the new key to the next GET.
    session[KEY_PLAIN_KEY] = new_key
    session[KEY_TIME_KEY] = time.time()
    return redirect(url_for('recovery.show_key'))


@recovery_bp.route('/recovery-key/continue', methods=['POST'])
def continue_after_key():
    flow = _get_key_flow()
    if flow is None:
        return _no_flow_redirect()

    _user_id, next_step = flow

    if not request.form.get('confirmed'):
        flash('Please confirm that you have saved your recovery key.', 'error')
        return redirect(url_for('recovery.show_key'))

    return _finish_key_flow(next_step)


@recovery_bp.route('/recovery-key/skip', methods=['POST'])
def continue_without_key():
    """Continue from the 'already shown' state without a new key.

    The stored hash still matches the key the user saw. Only allowed once the
    key has been displayed; otherwise the user goes back to see it first.
    """
    flow = _get_key_flow()
    if flow is None:
        return _no_flow_redirect()

    _user_id, next_step = flow

    if session.get(KEY_PLAIN_KEY) is not None:
        return redirect(url_for('recovery.show_key'))

    return _finish_key_flow(next_step)
