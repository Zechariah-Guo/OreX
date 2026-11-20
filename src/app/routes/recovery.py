"""Account recovery routes: forgot password via a one-time recovery key.

Flow:
1. /forgot-password  - username + recovery key. Failures share the login rate
   limiter (``app.routes.auth``) and always return the same generic message.
2. /reset-password   - new password (twice), only reachable through a short-lived
   (5 minute) session holding the verified user id.

The reset page also offers an optional new recovery key, shown inside the form
(see ``app.recovery_form``). The old key is consumed and the new key hash is
stored in the same transaction as the password change; nothing is stored
before that, and the plain key is never kept server-side.
"""

import time

from flask import (
    Blueprint, render_template, redirect, url_for, flash, request, session
)
from flask_login import current_user

from app.models import (
    get_user_by_id,
    get_user_by_username,
    get_recovery_key_hash,
    reset_password_with_recovery_key,
)
from app.recovery_form import (
    RESET_TOKEN_MAX_AGE,
    fresh_option,
    read_option,
    render_no_store,
)
from app.totp import hash_recovery_key, verify_recovery_key
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
        # Ticked by default: the user has just used up their only key.
        return render_no_store(
            'pages/reset_password.html',
            **fresh_option('reset', user_id, default_wanted=True).context,
        )

    password = request.form.get('password', '')
    confirm_password = request.form.get('confirm_password', '')

    option = read_option(
        request.form, 'reset', user_id, max_age=RESET_TOKEN_MAX_AGE
    )

    def render(**errors):
        # Same pending session and same key (re-signed) so a saved copy stays valid.
        return render_no_store('pages/reset_password.html', **option.context, **errors)

    valid, error = validate_password(password)
    if not valid:
        return render(password_error=error)

    if password != confirm_password:
        return render(confirm_error='Passwords do not match.')

    if option.error:
        return render()

    if get_user_by_id(user_id) is None:
        _clear_pending_reset()
        flash('Your password reset session has expired. Please start again.', 'error')
        return redirect(url_for('recovery.forgot_password'))

    # One transaction: consume the old key (single use, checked by row count),
    # set the password and store the new key hash (only if one was requested).
    # If the old key was already used (another tab) nothing changes.
    old_key_hash = session.get(PENDING_RESET_KEYHASH_KEY)
    new_key_hash = hash_recovery_key(option.key) if option.key else None
    if not old_key_hash or not reset_password_with_recovery_key(
        user_id, old_key_hash, generate_password_hash(password), new_key_hash
    ):
        _clear_pending_reset()
        flash('Your password reset session has expired. Please start again.', 'error')
        return redirect(url_for('recovery.forgot_password'))

    _clear_pending_reset()
    flash('Your password has been reset. Please log in with your new password.', 'success')
    return redirect(url_for('auth.login'))
