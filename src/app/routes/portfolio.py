"""Portfolio routes: view user holdings."""

import json

from flask import Blueprint, render_template, request
from flask_login import login_required, current_user

from app.models import get_holdings_by_user, get_user_by_id

portfolio_bp = Blueprint('portfolio', __name__)


@portfolio_bp.route('/portfolio')
@login_required
def overview():
    """Display the user's portfolio with holdings and profit/loss."""
    user = get_user_by_id(current_user.id)
    holdings = get_holdings_by_user(current_user.id)

    # Calculate portfolio totals
    total_invested = 0
    total_current_value = 0
    holdings_data = []

    for h in holdings:
        invested = h['quantity'] * h['avg_purchase_price']
        current_value = h['quantity'] * h['current_price']
        profit_loss = current_value - invested
        profit_loss_pct = ((current_value / invested) - 1) * 100 if invested > 0 else 0

        total_invested += invested
        total_current_value += current_value

        holdings_data.append({
            'ore_id': h['ore_id'],
            'name': h['name'],
            'icon_filename': h['icon_filename'],
            'quantity': h['quantity'],
            'avg_purchase_price': h['avg_purchase_price'],
            'current_price': h['current_price'],
            'invested': invested,
            'current_value': current_value,
            'profit_loss': profit_loss,
            'profit_loss_pct': profit_loss_pct,
            'last_movement': json.loads(h['trend_log'])[-1] if h['trend_log'] else 'hold',
        })

    total_profit_loss = total_current_value - total_invested
    total_portfolio_value = user.balance + total_current_value

    # HTMX partial: return only the live content
    if request.headers.get('HX-Request'):
        return render_template('partials/portfolio_live.html',
                               user=user,
                               holdings=holdings_data,
                               total_current_value=total_current_value,
                               total_profit_loss=total_profit_loss,
                               total_portfolio_value=total_portfolio_value)

    return render_template('pages/portfolio.html',
                           user=user,
                           holdings=holdings_data,
                           total_invested=total_invested,
                           total_current_value=total_current_value,
                           total_profit_loss=total_profit_loss,
                           total_portfolio_value=total_portfolio_value)
