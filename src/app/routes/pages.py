"""Static pages: landing, about, help."""

import json

from flask import Blueprint, current_app, render_template, redirect, request, url_for
from flask_login import current_user

from app.models import get_all_ores

pages_bp = Blueprint('pages', __name__)


def _market_ticker():
    """Public snapshot of the 9 ores for the landing page's live strip.

    Only the fields the strip shows: name, icon, price and last move. Prices
    are game data, safe to show logged-out.
    """
    ticker = []
    for ore in get_all_ores():
        try:
            trend = json.loads(ore['trend_log'])[-1] if ore['trend_log'] else 'hold'
        except (ValueError, IndexError, TypeError):
            trend = 'hold'
        ticker.append({
            'name': ore['name'],
            'icon_filename': ore['icon_filename'],
            'price': ore['current_price'],
            'trend': trend if trend in ('rise', 'fall') else 'hold',
        })
    return ticker


@pages_bp.route('/')
def landing():
    """Landing page - redirect to dashboard if already logged in.

    htmx requests (the strip's 20s refresh) get just the live market strip.
    """
    if current_user.is_authenticated:
        return redirect(url_for('dashboard.overview'))

    ticker = _market_ticker()
    if request.headers.get('HX-Request'):
        return render_template('partials/landing_ticker.html', ticker=ticker)

    return render_template(
        'pages/landing.html',
        ticker=ticker,
        starting_balance=current_app.config['DEFAULT_BALANCE'],
        advanced_threshold=current_app.config['ADVANCED_MODE_THRESHOLD'],
        advanced_cost=current_app.config['ADVANCED_MODE_COST'],
        bonus_amounts=current_app.config['BONUS_AMOUNTS'],
    )


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
