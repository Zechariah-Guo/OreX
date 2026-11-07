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
    """Help / FAQ page, with the tutorial list for logged-in players."""
    tutorials = None  # None = logged out: the page shows a login hint instead
    if current_user.is_authenticated:
        from app.advanced import get_advanced_status
        from app.tutorial.data import load_all_tracks
        from app.tutorial.models import get_all_tutorial_states
        from app.tutorial.view import build_tutorial_list

        status = get_advanced_status(current_user.id)
        tutorials = build_tutorial_list(
            load_all_tracks(),
            get_all_tutorial_states(current_user.id),
            status['purchased'],
            status['active'],
        )
    return render_template('pages/help.html', tutorials=tutorials)
