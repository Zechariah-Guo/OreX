"""Dashboard route: at-a-glance overview of user's portfolio and market."""

from flask import Blueprint, render_template, request
from flask_login import login_required, current_user

from app.models import (
    get_user_by_id, get_holdings_by_user, get_portfolio_value,
    get_portfolio_cost, get_top_movers, get_recent_transactions
)

dashboard_bp = Blueprint('dashboard', __name__)


@dashboard_bp.route('/dashboard')
@login_required
def overview():
    """User dashboard with portfolio summary, top movers, and recent activity."""
    user = get_user_by_id(current_user.id)
    holdings = get_holdings_by_user(current_user.id)

    portfolio_value = get_portfolio_value(current_user.id)
    portfolio_cost = get_portfolio_cost(current_user.id)
    total_value = user.balance + portfolio_value
    profit_loss = portfolio_value - portfolio_cost

    top_movers = get_top_movers(limit=5)
    recent_transactions = get_recent_transactions(current_user.id, limit=5)

    # HTMX partial: return only the dynamic sections
    if request.headers.get('HX-Request'):
        return render_template('partials/dashboard_live.html',
                               user=user,
                               portfolio_value=portfolio_value,
                               total_value=total_value,
                               profit_loss=profit_loss,
                               top_movers=top_movers,
                               recent_transactions=recent_transactions)

    return render_template('pages/dashboard.html',
                           user=user,
                           holdings=holdings,
                           portfolio_value=portfolio_value,
                           total_value=total_value,
                           profit_loss=profit_loss,
                           top_movers=top_movers,
                           recent_transactions=recent_transactions)
