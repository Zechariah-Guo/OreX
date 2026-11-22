"""Account settings: password change, account reset, and account deletion."""

import logging

from flask import Blueprint, render_template, redirect, url_for, flash, request, current_app
from flask_login import login_required, login_user, logout_user, current_user

from app.models import (
    get_user_by_id, get_user_by_username, verify_password,
    update_password, reset_account, delete_account, get_2fa_status,
    get_net_worth, get_notification_style, revoke_all_sessions,
)
from app.advancements import evaluate_post_mortem
from app.database import get_db
from app.utils.validation import validate_password
from app.advanced import purchase_advanced_mode, toggle_advanced_mode

logger = logging.getLogger(__name__)

settings_bp = Blueprint('settings', __name__)


@settings_bp.context_processor
def push_card_context():
    """Data for the Notifications card, on every settings page render."""
    if not current_user.is_authenticated:
        return {}
    from flask import current_app
    from app import push
    prefs = push.get_preferences(get_db(), current_user.id)
    return {
        'push_configured': push.is_configured(current_app.config),
        'push_public_key': current_app.config['VAPID_PUBLIC_KEY'],
        'push_groups': [
            {
                'key': group, 'label': push.GROUP_LABELS[group], 'on': prefs[group],
                # Group keys equal inbox categories: same icon and colour as the inbox list
                'css_class': get_notification_style(group)[0],
                'icon': get_notification_style(group)[1],
            }
            for group in push.GROUPS
        ],
    }


def _keep_this_session_signed_in():
    """Sign this browser back in under the player's new session version.

    Password change and account reset raise users.session_version, which signs
    out every session and remember cookie. This one is re-issued so the player
    who just made the change stays signed in; a device that had a remember cookie
    keeps remembering.
    """
    remember = current_app.config.get('REMEMBER_COOKIE_NAME', 'remember_token') in request.cookies
    user = get_user_by_id(current_user.id)
    if user is not None:
        login_user(user, remember=remember)


@settings_bp.route('/settings')
@login_required
def overview():
    """Account settings page."""
    user = get_user_by_id(current_user.id)
    two_factor_enabled = get_2fa_status(current_user.id)['enabled']
    return render_template(
        'pages/settings.html', user=user, two_factor_enabled=two_factor_enabled
    )


@settings_bp.route('/settings/password', methods=['POST'])
@login_required
def change_password():
    """Change the user's password."""
    current_password = request.form.get('current_password', '')
    new_password = request.form.get('new_password', '')
    confirm_password = request.form.get('confirm_password', '')

    # Verify current password
    user_row = get_user_by_username(current_user.username)
    if not verify_password(user_row['password_hash'], current_password):
        user = get_user_by_id(current_user.id)
        return render_template(
            'pages/settings.html',
            user=user,
            two_factor_enabled=get_2fa_status(current_user.id)['enabled'],
            current_password_error='Current password is incorrect.',
        )

    # Check new password is not the same as current
    if new_password == current_password:
        user = get_user_by_id(current_user.id)
        return render_template(
            'pages/settings.html',
            user=user,
            two_factor_enabled=get_2fa_status(current_user.id)['enabled'],
            password_error='New password cannot match old password',
        )

    # Validate new password
    valid, error = validate_password(new_password)
    if not valid:
        user = get_user_by_id(current_user.id)
        return render_template(
            'pages/settings.html',
            user=user,
            two_factor_enabled=get_2fa_status(current_user.id)['enabled'],
            password_error=error,
        )

    if new_password != confirm_password:
        user = get_user_by_id(current_user.id)
        return render_template(
            'pages/settings.html',
            user=user,
            two_factor_enabled=get_2fa_status(current_user.id)['enabled'],
            confirm_error='New passwords do not match.',
        )

    update_password(current_user.id, new_password)
    _keep_this_session_signed_in()
    flash('Password updated successfully.', 'success')
    return redirect(url_for('settings.overview', _anchor='account'))


@settings_bp.route('/settings/sign-out-others', methods=['POST'])
@login_required
def sign_out_others():
    """Sign out every other device, keeping this browser signed in."""
    revoke_all_sessions(current_user.id)
    _keep_this_session_signed_in()
    flash('Signed out of all other devices.', 'success')
    return redirect(url_for('settings.overview', _anchor='account'))


@settings_bp.route('/settings/reset', methods=['GET', 'POST'])
@login_required
def reset():
    """Account reset — requires username confirmation."""
    if request.method == 'POST':
        confirmation = request.form.get('confirmation', '').strip()

        if confirmation != current_user.username:
            flash('Username confirmation does not match. Account was not reset.', 'error')
            return redirect(url_for('settings.reset'))

        # Evaluate post-mortem (tragedy) achievement before reset clears data
        try:
            db = get_db()
            net_worth = get_net_worth(current_user.id)
            evaluate_post_mortem(db, current_user.id, net_worth)
        except Exception:
            logger.exception("Failed to evaluate post-mortem advancements for user %s", current_user.id)

        reset_account(current_user.id)
        _keep_this_session_signed_in()
        flash('Account has been reset. Your balance has been restored and holdings cleared.', 'liquidation')
        return redirect(url_for('dashboard.overview'))

    return render_template('pages/reset_confirm.html')


@settings_bp.route('/settings/delete', methods=['GET', 'POST'])
@login_required
def delete():
    """Account deletion — requires username confirmation."""
    if request.method == 'POST':
        confirmation = request.form.get('confirmation', '').strip()

        if confirmation != current_user.username:
            flash('Username confirmation does not match. Account was not deleted.', 'error')
            return redirect(url_for('settings.delete'))

        user_id = current_user.id
        logout_user()
        delete_account(user_id)
        flash('Your account has been permanently deleted.', 'liquidation')
        return redirect(url_for('pages.landing'))

    return render_template('pages/delete_confirm.html')


@settings_bp.route('/settings/advanced/purchase', methods=['POST'])
@login_required
def purchase_advanced():
    """Purchase Advanced Mode for the current user."""
    success, message = purchase_advanced_mode(current_user.id)
    flash(message, 'success' if success else 'error')
    return redirect(url_for('settings.overview', _anchor='gameplay'))


@settings_bp.route('/settings/advanced/toggle', methods=['POST'])
@login_required
def toggle_advanced():
    """Toggle Advanced Mode on or off for the current user."""
    success, message = toggle_advanced_mode(current_user.id)
    flash(message, 'success' if success else 'error')
    return redirect(url_for('settings.overview', _anchor='gameplay'))
