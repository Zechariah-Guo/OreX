"""Account settings: password change, account reset, and account deletion."""

from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required, logout_user, current_user

from app.models import (
    get_user_by_id, get_user_by_username, verify_password,
    update_password, reset_account, delete_account
)
from app.utils.validation import validate_password

settings_bp = Blueprint('settings', __name__)


@settings_bp.route('/settings')
@login_required
def overview():
    """Account settings page."""
    user = get_user_by_id(current_user.id)
    return render_template('pages/settings.html', user=user)


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
            current_password_error='Current password is incorrect.',
        )

    # Check new password is not the same as current
    if new_password == current_password:
        user = get_user_by_id(current_user.id)
        return render_template(
            'pages/settings.html',
            user=user,
            password_error='New password cannot match old password',
        )

    # Validate new password
    valid, error = validate_password(new_password)
    if not valid:
        user = get_user_by_id(current_user.id)
        return render_template(
            'pages/settings.html',
            user=user,
            password_error=error,
        )

    if new_password != confirm_password:
        user = get_user_by_id(current_user.id)
        return render_template(
            'pages/settings.html',
            user=user,
            confirm_error='New passwords do not match.',
        )

    update_password(current_user.id, new_password)
    flash('Password updated successfully.', 'success')
    return redirect(url_for('settings.overview'))


@settings_bp.route('/settings/reset', methods=['GET', 'POST'])
@login_required
def reset():
    """Account reset — requires username confirmation."""
    if request.method == 'POST':
        confirmation = request.form.get('confirmation', '').strip()

        if confirmation != current_user.username:
            flash('Username confirmation does not match. Account was not reset.', 'error')
            return redirect(url_for('settings.reset'))

        reset_account(current_user.id)
        flash('Account has been reset. Your balance has been restored and holdings cleared.', 'success')
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
        flash('Your account has been permanently deleted.', 'success')
        return redirect(url_for('pages.landing'))

    return render_template('pages/delete_confirm.html')
