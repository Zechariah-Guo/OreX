"""Static pages: landing, about, help."""

from flask import Blueprint, render_template, redirect, url_for
from flask_login import current_user

pages_bp = Blueprint('pages', __name__)


@pages_bp.route('/')
def landing():
    """Landing page - redirect to dashboard if already logged in."""
    if current_user.is_authenticated:
        return redirect(url_for('dashboard.overview'))
    return render_template('pages/landing.html')


@pages_bp.route('/about')
def about():
    """About / How It Works page."""
    return render_template('pages/about.html')


@pages_bp.route('/help')
def help_page():
    """Help / FAQ page."""
    return render_template('pages/help.html')
