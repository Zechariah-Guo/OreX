"""Static pages: landing, about, help."""

import json

from flask import (Blueprint, Response, current_app, render_template, redirect, request,
                   send_from_directory, url_for)
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


PWA_ICON_DIR = '/static/images/pwa/'
PWA_ICON_SIZES = (128, 192, 384, 512)


def _pwa_manifest():
    """Web app manifest. Absolute /static paths so they resolve from any URL."""
    icons = []
    for size in PWA_ICON_SIZES:
        icons.append({'src': f'{PWA_ICON_DIR}icon-{size}x{size}.png',
                      'sizes': f'{size}x{size}', 'type': 'image/png', 'purpose': 'any'})
        icons.append({'src': f'{PWA_ICON_DIR}maskable_icon_x{size}.png',
                      'sizes': f'{size}x{size}', 'type': 'image/png', 'purpose': 'maskable'})
    return {
        'id': '/',
        'name': 'OreX',
        'short_name': 'OreX',
        'description': 'A Minecraft-themed stock market simulation. Trade ores and build your fortune.',
        'start_url': '/',
        'scope': '/',
        'display': 'standalone',
        'background_color': '#f5f2f9',
        'theme_color': '#ffffff',
        'icons': icons,
        'screenshots': [
            {'src': f'{PWA_ICON_DIR}desktop_screenshot.png', 'sizes': '1522x787',
             'type': 'image/png', 'form_factor': 'wide', 'label': 'OreX on desktop'},
            {'src': f'{PWA_ICON_DIR}mobile_screenshot.png', 'sizes': '771x1600',
             'type': 'image/png', 'form_factor': 'narrow', 'label': 'OreX on mobile'},
        ],
    }


@pages_bp.route('/manifest.webmanifest')
def manifest():
    """PWA manifest (public, no login)."""
    return Response(json.dumps(_pwa_manifest()), mimetype='application/manifest+json')


@pages_bp.route('/sw.js')
def service_worker():
    """Service worker, served from the site root so its scope is '/'.

    no-cache makes the browser revalidate it on every check, so an updated
    worker is picked up. See static/js/sw.js for what it does (and does not) cache.
    """
    response = send_from_directory(current_app.static_folder, 'js/sw.js',
                                   mimetype='text/javascript', max_age=0)
    response.headers['Cache-Control'] = 'no-cache'
    return response


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
