"""Authentication routes: register, login, logout."""

import time
from math import ceil

from flask import Blueprint, render_template, redirect, url_for, flash, request, current_app, session
from flask_login import login_user, logout_user, login_required, current_user

from app.models import (
    User, create_user, get_user_by_username,
    verify_password, update_last_login, get_2fa_status
)
from app.utils.validation import validate_username, validate_password
from app.recovery_form import fresh_option, read_option, render_no_store
from app.totp import hash_recovery_key
from app.database import get_db
from app.advancements import update_login_streak

auth_bp = Blueprint('auth', __name__)

# In-memory rate limiter (resets on server restart)
_login_attempts = {}  # {ip_address: [timestamp, timestamp, ...]}

# Pre-computed dummy hash for timing-attack mitigation.
# Used when a login attempt references a nonexistent username so that
# response time is indistinguishable from a real password check.
from werkzeug.security import generate_password_hash
_DUMMY_HASH = generate_password_hash('dummy-password-for-timing-safety')


def _is_rate_limited(ip):
    """Check if an IP has exceeded the login attempt limit."""
    window = current_app.config['RATE_LIMIT_WINDOW']
    max_attempts = current_app.config['RATE_LIMIT_MAX']
    now = time.time()

    if ip not in _login_attempts:
        _login_attempts[ip] = []

    # Remove attempts outside the window
    _login_attempts[ip] = [t for t in _login_attempts[ip] if now - t < window]

    return len(_login_attempts[ip]) >= max_attempts


def _record_attempt(ip):
    """Record a login attempt for rate limiting."""
    if ip not in _login_attempts:
        _login_attempts[ip] = []
    _login_attempts[ip].append(time.time())


def _rate_limit_retry_minutes(ip):
    """Return the number of whole minutes until the login window clears."""
    window = current_app.config['RATE_LIMIT_WINDOW']
    now = time.time()
    attempts = _login_attempts.get(ip, [])
    if not attempts:
        return 0
    oldest_attempt = min(attempts)
    remaining_seconds = max(0, window - (now - oldest_attempt))
    return max(1, ceil(remaining_seconds / 60))


@auth_bp.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard.overview'))

    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        confirm_password = request.form.get('confirm_password', '')

        # Optional inline recovery key (signed token + "I have saved" confirmation).
        option = read_option(request.form, 'register')

        def render(**errors):
            # The page holds a key, so it is never cached. A failed submit keeps
            # the same key (re-signed) so a copy the user already saved stays valid.
            return render_no_store(
                'pages/register.html', username=username, **option.context, **errors
            )

        # Validate inputs
        valid, error = validate_username(username)
        if not valid:
            return render(username_error=error)

        valid, error = validate_password(password)
        if not valid:
            return render(password_error=error)

        if password != confirm_password:
            return render(confirm_error='Passwords do not match.')

        # Check uniqueness
        if get_user_by_username(username):
            return render(username_error='That username is already taken.')

        if option.error:
            return render()

        # Create the user (and the recovery key hash, if wanted) in one transaction, then log in
        recovery_hash = hash_recovery_key(option.key) if option.key else None
        user_id = create_user(username, password, recovery_hash)
        user = User(user_id, username, current_app.config['DEFAULT_BALANCE'])
        # Registering on a device implies staying signed in on it
        login_user(user, remember=True)
        update_last_login(user_id)

        flash('Account created successfully. Welcome to OreX!', 'success')
        return redirect(url_for('dashboard.overview'))

    return render_no_store(
        'pages/register.html', **fresh_option('register').context
    )


@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard.overview'))

    if request.method == 'POST':
        ip = request.remote_addr

        # Rate limit check
        if _is_rate_limited(ip):
            minutes = _rate_limit_retry_minutes(ip)
            return render_template(
                'pages/login.html',
                login_error=f'Too many login attempts. Please try again in {minutes} minutes.',
            )

        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')

        if not username or not password:
            return render_template(
                'pages/login.html',
                username=username,
                login_error='Please enter both username and password.',
            )

        # Look up user
        row = get_user_by_username(username)
        if not row:
            # Perform a dummy hash check to prevent timing-based username
            # enumeration (response time is consistent whether user exists or not)
            verify_password(_DUMMY_HASH, password)
            _record_attempt(ip)
            return render_template(
                'pages/login.html',
                username=username,
                login_error='Invalid username or password.',
            )

        if not verify_password(row['password_hash'], password):
            _record_attempt(ip)
            return render_template(
                'pages/login.html',
                username=username,
                login_error='Invalid username or password.',
            )

        # Suspended accounts (scripts/admin/suspend_user.py): checked after the
        # password so the message is only shown to someone who knows it.
        if row['suspended_at']:
            return render_template(
                'pages/login.html',
                username=username,
                login_error='This account has been suspended. Contact orexsupport@gmail.com.',
            )

        # "Stay signed in" checkbox: remember the player for 30 days when ticked
        remember = bool(request.form.get('remember'))

        # Check if 2FA is enabled for this user
        tfa_status = get_2fa_status(row['id'])
        if tfa_status['enabled']:
            session['pending_2fa_user_id'] = row['id']
            session['pending_2fa_time'] = time.time()
            session['pending_2fa_remember'] = remember
            return redirect(url_for('two_factor.challenge'))

        # Login successful
        user = User(row['id'], row['username'], row['balance'], row['session_version'])
        login_user(user, remember=remember)
        update_last_login(row['id'])

        # Update login streak and evaluate streak-based advancements
        try:
            db = get_db()
            update_login_streak(db, row['id'])
            db.commit()
        except Exception:
            pass

        flash(f'Welcome back, {user.username}!', 'success')

        # Redirect to the page they were trying to access, or dashboard
        next_page = request.args.get('next')
        if next_page:
            return redirect(next_page)
        return redirect(url_for('dashboard.overview'))

    return render_template('pages/login.html')


@auth_bp.route('/logout')
@login_required
def logout():
    logout_user()
    flash('You have been logged out.', 'success')
    return redirect(url_for('pages.landing'))
