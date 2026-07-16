"""Two-factor authentication routes.

Challenge routes (this task): the post-password TOTP/backup-code challenge
that completes login for users with 2FA enabled.

Setup and disable routes are added to this same blueprint in a later task.

The existing login rate limiter (defined in ``app.routes.auth``) is reused so
that failed 2FA attempts share the same per-IP counter as failed password
attempts (Requirement 6.3).
"""

import base64
import time

from flask import (
    Blueprint, render_template, redirect, url_for, flash, request, session
)
from flask_login import login_user, login_required, current_user

from app.models import (
    get_user_by_id,
    get_2fa_status,
    enable_2fa,
    disable_2fa,
    get_encrypted_totp_secret,
    store_backup_codes,
    get_backup_codes,
    mark_backup_code_used,
)
from app.totp import (
    generate_secret,
    get_provisioning_uri,
    generate_qr_code,
    verify_totp,
    encrypt_secret,
    decrypt_secret,
    hash_backup_code,
    generate_backup_codes,
    verify_backup_code,
)

# Reuse the existing login rate limiter so 2FA attempts count toward the same
# per-IP window as password attempts (do NOT create a new limiter).
from app.routes.auth import (
    _is_rate_limited,
    _record_attempt,
    _rate_limit_retry_minutes,
)
from flask import current_app  # noqa: E402  (kept close to usage below)

two_factor_bp = Blueprint('two_factor', __name__)

# Session keys for the pending 2FA state (see design.md).
PENDING_USER_KEY = 'pending_2fa_user_id'
PENDING_TIME_KEY = 'pending_2fa_time'

# Pending session validity window in seconds (5 minutes).
PENDING_SESSION_TTL = 300

# Session key holding the transient TOTP secret generated during setup but not
# yet confirmed/enabled. It lets /confirm verify the entered code against the
# same secret shown on /setup without enabling 2FA prematurely (Req 2.3).
PENDING_SETUP_SECRET_KEY = 'pending_2fa_setup_secret'

# Number of backup codes generated on successful 2FA confirmation (Req 3.1).
BACKUP_CODE_COUNT = 8


def _clear_pending_session():
    """Remove pending 2FA state from the session."""
    session.pop(PENDING_USER_KEY, None)
    session.pop(PENDING_TIME_KEY, None)


def _get_pending_user_id():
    """Return the pending 2FA user id if a valid, non-expired session exists.

    Returns None when there is no pending session or when it has expired.
    Expired sessions are cleared as a side effect.
    """
    user_id = session.get(PENDING_USER_KEY)
    created_at = session.get(PENDING_TIME_KEY)

    if user_id is None or created_at is None:
        return None

    # Expiry boundary: valid while elapsed < TTL, expired at elapsed >= TTL.
    if time.time() - created_at >= PENDING_SESSION_TTL:
        _clear_pending_session()
        return None

    return user_id


def _complete_login(user_id):
    """Fully authenticate the user and clear the pending 2FA session."""
    user = get_user_by_id(user_id)
    if user is None:
        # User disappeared between password step and challenge; bail out.
        _clear_pending_session()
        return None

    _clear_pending_session()
    login_user(user)
    return user


@two_factor_bp.route('/login/2fa', methods=['GET'])
def challenge():
    """Render the 2FA challenge page.

    Requires an active, non-expired pending 2FA session; otherwise the user is
    redirected back to the login page (prevents direct access).
    """
    if current_user.is_authenticated:
        return redirect(url_for('dashboard.overview'))

    user_id = _get_pending_user_id()
    if user_id is None:
        flash('Your login session has expired. Please log in again.', 'error')
        return redirect(url_for('auth.login'))

    return render_template('pages/two_factor_challenge.html')


@two_factor_bp.route('/login/2fa', methods=['POST'])
def verify():
    """Verify a submitted TOTP code and complete login."""
    if current_user.is_authenticated:
        return redirect(url_for('dashboard.overview'))

    user_id = _get_pending_user_id()
    if user_id is None:
        flash('Your login session has expired. Please log in again.', 'error')
        return redirect(url_for('auth.login'))

    ip = request.remote_addr

    # Shared rate limiter with password attempts.
    if _is_rate_limited(ip):
        minutes = _rate_limit_retry_minutes(ip)
        return render_template(
            'pages/two_factor_challenge.html',
            login_error=f'Too many attempts. Please try again in {minutes} minutes.',
        )

    code = request.form.get('code', '').strip()

    encrypted_secret = get_encrypted_totp_secret(user_id)
    if not encrypted_secret:
        # 2FA is not actually configured for this account — cannot verify.
        _clear_pending_session()
        flash('Two-factor authentication is not configured. Please log in again.', 'error')
        return redirect(url_for('auth.login'))

    try:
        secret = decrypt_secret(encrypted_secret, current_app.config['SECRET_KEY'])
    except Exception:
        # Corrupted or undecryptable secret — deny login (see design error table).
        _clear_pending_session()
        flash('Two-factor configuration error — please contact support.', 'error')
        return redirect(url_for('auth.login'))

    if not code or not verify_totp(secret, code):
        _record_attempt(ip)
        return render_template(
            'pages/two_factor_challenge.html',
            login_error='Invalid authentication code.',
        )

    user = _complete_login(user_id)
    if user is None:
        flash('Your account could not be found. Please log in again.', 'error')
        return redirect(url_for('auth.login'))

    flash(f'Welcome back, {user.username}!', 'success')
    return redirect(url_for('dashboard.overview'))


@two_factor_bp.route('/login/2fa/backup', methods=['POST'])
def verify_backup():
    """Verify a submitted backup code, mark it used, and complete login."""
    if current_user.is_authenticated:
        return redirect(url_for('dashboard.overview'))

    user_id = _get_pending_user_id()
    if user_id is None:
        flash('Your login session has expired. Please log in again.', 'error')
        return redirect(url_for('auth.login'))

    ip = request.remote_addr

    # Shared rate limiter with password attempts.
    if _is_rate_limited(ip):
        minutes = _rate_limit_retry_minutes(ip)
        return render_template(
            'pages/two_factor_challenge.html',
            show_backup=True,
            login_error=f'Too many attempts. Please try again in {minutes} minutes.',
        )

    code = request.form.get('backup_code', '').strip()

    matched_code_id = None
    if code:
        for entry in get_backup_codes(user_id):
            if entry['used']:
                continue
            if verify_backup_code(entry['code_hash'], code):
                matched_code_id = entry['id']
                break

    if matched_code_id is None:
        _record_attempt(ip)
        return render_template(
            'pages/two_factor_challenge.html',
            show_backup=True,
            login_error='Invalid or already-used backup code.',
        )

    # Invalidate the code permanently before completing login (single-use).
    mark_backup_code_used(matched_code_id)

    user = _complete_login(user_id)
    if user is None:
        flash('Your account could not be found. Please log in again.', 'error')
        return redirect(url_for('auth.login'))

    flash(f'Welcome back, {user.username}!', 'success')
    return redirect(url_for('dashboard.overview'))


def _render_setup(secret, **extra):
    """Render the 2FA setup interface for the given (pending) secret.

    Builds the provisioning URI, renders it as a base64-encoded QR code for
    inline display, and exposes the base32 secret as the manual key. Extra
    keyword args (e.g. ``setup_error``) are forwarded to the template.
    """
    uri = get_provisioning_uri(secret, current_user.username)
    png_bytes = generate_qr_code(uri)
    qr_code_b64 = base64.b64encode(png_bytes).decode('ascii')
    return render_template(
        'pages/two_factor_setup.html',
        qr_code_b64=qr_code_b64,
        manual_key=secret,
        **extra,
    )


@two_factor_bp.route('/settings/2fa/setup', methods=['POST'])
@login_required
def setup():
    """Begin 2FA setup: generate a new secret and show the QR code + manual key.

    The secret is stored transiently in the session (NOT persisted / enabled)
    so that ``confirm`` can verify the entered code against it (Req 1.3-1.5).
    """
    status = get_2fa_status(current_user.id)
    if status['enabled']:
        flash('Two-factor authentication is already enabled.', 'info')
        return redirect(url_for('settings.overview'))

    secret = generate_secret()
    session[PENDING_SETUP_SECRET_KEY] = secret

    return _render_setup(secret)


@two_factor_bp.route('/settings/2fa/confirm', methods=['POST'])
@login_required
def confirm():
    """Confirm 2FA setup by verifying a TOTP code, then enable and show codes.

    On success: encrypt and persist the secret, mark 2FA enabled, generate and
    store hashed backup codes, and display the plaintext codes exactly once
    (Req 2.1, 2.2, 3.1, 3.2). On an invalid code, re-render the setup page with
    the SAME secret (no regeneration, Req 2.3).
    """
    secret = session.get(PENDING_SETUP_SECRET_KEY)
    if not secret:
        # No pending setup — the flow must be restarted from settings.
        flash('Your 2FA setup session has expired. Please start again.', 'error')
        return redirect(url_for('settings.overview'))

    code = request.form.get('code', '').strip()

    if not code or not verify_totp(secret, code):
        # Re-render setup with the same secret; do NOT regenerate (Req 2.3).
        return _render_setup(
            secret,
            setup_error='Invalid authentication code. Please try again.',
        )

    # Valid code — enable 2FA and generate backup codes.
    encrypted_secret = encrypt_secret(secret, current_app.config['SECRET_KEY'])
    enable_2fa(current_user.id, encrypted_secret)

    # The pending secret is no longer needed once persisted.
    session.pop(PENDING_SETUP_SECRET_KEY, None)

    backup_codes = generate_backup_codes(BACKUP_CODE_COUNT)
    store_backup_codes(
        current_user.id,
        [hash_backup_code(c) for c in backup_codes],
    )

    flash('Two-factor authentication is now enabled.', 'success')
    # Display the plaintext backup codes exactly once (Req 3.2).
    return render_template(
        'pages/two_factor_setup.html',
        backup_codes=backup_codes,
        status={'enabled': True},
    )


@two_factor_bp.route('/settings/2fa/disable', methods=['POST'])
@login_required
def disable():
    """Disable 2FA after confirming identity with a TOTP or backup code.

    Requires a valid TOTP code OR an unused backup code (Req 8.2). On success,
    removes the secret and all backup codes via ``disable_2fa`` (Req 8.3). On an
    invalid code, flash an error and return to settings.
    """
    status = get_2fa_status(current_user.id)
    if not status['enabled']:
        flash('Two-factor authentication is not enabled.', 'info')
        return redirect(url_for('settings.overview'))

    code = request.form.get('code', '').strip()

    verified = False
    if code:
        # Try TOTP first.
        encrypted_secret = status['encrypted_secret']
        if encrypted_secret:
            try:
                secret = decrypt_secret(
                    encrypted_secret, current_app.config['SECRET_KEY']
                )
                if verify_totp(secret, code):
                    verified = True
            except Exception:
                # Corrupted secret — fall through to backup-code check.
                verified = False

        # Fall back to an unused backup code.
        if not verified:
            for entry in get_backup_codes(current_user.id):
                if entry['used']:
                    continue
                if verify_backup_code(entry['code_hash'], code):
                    verified = True
                    break

    if not verified:
        flash('Invalid authentication code. Two-factor authentication was not disabled.', 'error')
        return redirect(url_for('settings.overview'))

    disable_2fa(current_user.id)
    flash('Two-factor authentication has been disabled.', 'success')
    return redirect(url_for('settings.overview'))
