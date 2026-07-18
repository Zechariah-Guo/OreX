"""Market routes: overview and ore detail pages."""

import json

from flask import Blueprint, jsonify, render_template, request
from flask_login import login_required, current_user

from app.decorators import advanced_required
from app.market.levels import calculate_levels
from app.models import get_all_ores, get_ore_by_id, get_price_history, get_holding
from app.database import get_db
from app.market.shorting import _calculate_squeeze_price, _calculate_tick_fee, _get_ticks_per_hour

market_bp = Blueprint('market', __name__)


def _get_ores_data():
    """Parse ores with trend data for templates."""
    ores = get_all_ores()
    ores_data = []
    for ore in ores:
        trend_log = json.loads(ore['trend_log'])
        last_movement = trend_log[-1] if trend_log else 'hold'
        ores_data.append({
            'id': ore['id'],
            'name': ore['name'],
            'icon_filename': ore['icon_filename'],
            'current_price': ore['current_price'],
            'base_price': ore['base_price'],
            'volatility': ore['volatility'],
            'last_movement': last_movement,
        })
    return ores_data


@market_bp.route('/market')
@login_required
def overview():
    """Market overview showing all ores in a card grid."""
    ores_data = _get_ores_data()

    # HTMX partial: return only the price grid
    if request.headers.get('HX-Request'):
        return render_template('partials/ore_price_grid.html', ores=ores_data)

    return render_template('pages/market.html', ores=ores_data)


@market_bp.route('/market/<int:ore_id>')
@login_required
def ore_detail(ore_id):
    """Detail page for a single ore with buy/sell forms and price chart."""
    ore = get_ore_by_id(ore_id)
    if not ore:
        return render_template('pages/404.html'), 404

    # Parse JSON fields for display
    trend_log = json.loads(ore['trend_log'])
    last_movement = trend_log[-1] if trend_log else 'hold'

    # HTMX partial: return only the stats section
    if request.headers.get('HX-Request'):
        return render_template('partials/ore_detail_stats.html',
                               ore=ore,
                               last_movement=last_movement)

    # Get price history for chart (default: max = 7 days soft cap)
    history = get_price_history(ore_id, hours=24 * 7)
    if len(history) > 100:
        step = len(history) // 100
        history = history[::step]
    chart_data = [{'price': row['price'], 'time': row['created_at'], 'movement': row['movement']} for row in history]

    # Get user's current holding for this ore
    holding = get_holding(current_user.id, ore_id)
    holding_qty = holding['quantity'] if holding else 0

    return render_template('pages/ore_detail.html',
                           ore=ore,
                           last_movement=last_movement,
                           chart_data=chart_data,
                           holding_qty=holding_qty)


@market_bp.route('/market/<int:ore_id>/history')
@login_required
def ore_price_history(ore_id):
    """API endpoint: return price history JSON for a given time range."""
    ore = get_ore_by_id(ore_id)
    if not ore:
        return {'error': 'Not found'}, 404

    range_param = request.args.get('range', '1d')

    # Map range to hours (fractional for minutes)
    range_map = {
        '5m': 5/60,
        '15m': 15/60,
        '30m': 30/60,
        '1h': 1,
        '6h': 6,
        '12h': 12,
        '1d': 24,
        '3d': 24 * 3,
        '5d': 24 * 5,
        'max': 24 * 7,  # Soft cap: 7 days
    }

    hours = range_map.get(range_param, 24)

    history = get_price_history(ore_id, hours=hours)

    # Downsample if too many points (keep chart responsive)
    max_points = 100
    if len(history) > max_points:
        step = len(history) // max_points
        history = history[::step]

    chart_data = [{'price': row['price'], 'time': row['created_at'], 'movement': row['movement']} for row in history]

    return jsonify(chart_data)


@market_bp.route('/market/ore/<int:ore_id>/levels')
@login_required
@advanced_required
def ore_levels(ore_id):
    """Return resistance and support levels for an ore (Advanced Mode only)."""
    levels = calculate_levels(ore_id)
    return jsonify(levels)


@market_bp.route('/market/ore/<int:ore_id>/price')
@login_required
def ore_current_price(ore_id):
    """Return the current price of an ore as JSON."""
    ore = get_ore_by_id(ore_id)
    if not ore:
        return jsonify({'price': None}), 404
    return jsonify({'price': ore['current_price']})


@market_bp.route('/market/ore/<int:ore_id>/squeeze')
@login_required
@advanced_required
def ore_squeeze_price(ore_id):
    """Return the squeeze price for the current user's active short on this ore.

    Returns JSON with squeeze_price (float or null if no active short exists).
    """
    db = get_db()

    # Find active short position(s) for this user on this ore
    position = db.execute(
        """SELECT sp.share_quantity, sp.entry_price, sp.locked_collateral,
                  o.volatility
           FROM short_positions sp
           JOIN ores o ON sp.ore_id = o.id
           WHERE sp.user_id = ? AND sp.ore_id = ? AND sp.status = 'active'
           ORDER BY sp.opened_at ASC
           LIMIT 1""",
        (current_user.id, ore_id)
    ).fetchone()

    if not position:
        return jsonify({'squeeze_price': None})

    # Get user balance
    user_row = db.execute(
        "SELECT balance FROM users WHERE id = ?", (current_user.id,)
    ).fetchone()
    user_balance = user_row['balance'] if user_row else 0.0

    ticks_per_hour = _get_ticks_per_hour()

    squeeze_price = _calculate_squeeze_price(
        {
            'share_quantity': position['share_quantity'],
            'entry_price': position['entry_price'],
            'locked_collateral': position['locked_collateral'],
        },
        user_balance,
        position['volatility'],
        ticks_per_hour,
    )

    # Convert infinity to None for JSON serialization
    if squeeze_price == float('inf'):
        squeeze_price = None

    return jsonify({'squeeze_price': squeeze_price})
