"""Dashboard route: at-a-glance overview of user's portfolio and market."""

from flask import Blueprint, render_template, request
from flask_login import login_required, current_user

from app.models import (
    get_user_by_id, get_holdings_by_user, get_portfolio_value,
    get_portfolio_cost, get_top_movers, get_recent_transactions
)
from app.database import get_db
from app.advanced import is_advanced_active
from app.config import Config
from app.market.shorting import (
    _calculate_tick_fee,
    _calculate_squeeze_price,
    _get_ticks_per_hour,
)

dashboard_bp = Blueprint('dashboard', __name__)


def _get_short_position_cards(user_id: int) -> list:
    """Build display data for each active short position including P/L, squeeze price, fee rate.

    Queries all active short positions for the user joined with the ores table,
    then computes derived display values for each position.

    Returns:
        List of dicts, each containing:
        - id: position ID
        - ore_name: name of the shorted ore
        - ore_id: ore identifier
        - share_quantity: number of shares shorted
        - entry_price: price at which the short was opened
        - current_price: current ore market price
        - short_value: current cost to buy back (shares × current_price)
        - unrealized_pnl: profit/loss if closed now (entry_price × shares - short_value)
        - locked_collateral: currently locked collateral
        - squeeze_price: estimated price at which FreeCash would be exhausted
        - tick_fee: per-tick fee at current volatility
        - cumulative_fees_paid: total fees paid so far
    """
    db = get_db()

    positions = db.execute(
        """SELECT sp.id, sp.ore_id, sp.share_quantity, sp.entry_price,
                  sp.locked_collateral, sp.cumulative_fees_paid,
                  sp.stop_loss_price, sp.take_profit_price, sp.opened_at,
                  o.name AS ore_name, o.current_price, o.volatility
           FROM short_positions sp
           JOIN ores o ON sp.ore_id = o.id
           WHERE sp.user_id = ? AND sp.status = 'active'
           ORDER BY sp.opened_at ASC""",
        (user_id,)
    ).fetchall()

    if not positions:
        return []

    # Get user balance for squeeze price calculation
    user_row = db.execute(
        "SELECT balance FROM users WHERE id = ?", (user_id,)
    ).fetchone()
    user_balance = user_row['balance'] if user_row else 0.0

    ticks_per_hour = _get_ticks_per_hour()
    cards = []

    for pos in positions:
        shares = pos['share_quantity']
        current_price = pos['current_price']
        entry_price = pos['entry_price']
        volatility = pos['volatility']

        short_value = shares * current_price
        unrealized_pnl = (entry_price * shares) - short_value

        tick_fee = _calculate_tick_fee(short_value, volatility, ticks_per_hour)

        squeeze_price = _calculate_squeeze_price(
            {
                'share_quantity': shares,
                'entry_price': entry_price,
                'locked_collateral': pos['locked_collateral'],
            },
            user_balance,
            volatility,
            ticks_per_hour,
        )

        cards.append({
            'id': pos['id'],
            'ore_name': pos['ore_name'],
            'ore_id': pos['ore_id'],
            'share_quantity': shares,
            'entry_price': entry_price,
            'current_price': current_price,
            'short_value': round(short_value, 2),
            'unrealized_pnl': round(unrealized_pnl, 2),
            'locked_collateral': pos['locked_collateral'],
            'squeeze_price': squeeze_price,
            'tick_fee': tick_fee,
            'cumulative_fees_paid': pos['cumulative_fees_paid'],
            'stop_loss_price': pos['stop_loss_price'],
            'take_profit_price': pos['take_profit_price'],
            'opened_at': pos['opened_at'],
        })

    return cards


def _get_threat_horizon_data(user_id: int) -> dict:
    """Calculate FreeCash runway: color code, tick countdown, aggregate fee rate.

    Determines how many ticks the user's FreeCash can sustain at the current
    aggregate fee rate across all active short positions.

    Color coding:
    - green: FreeCash covers more than 60 ticks of fees
    - amber: FreeCash covers 20–60 ticks of fees
    - red: FreeCash covers fewer than 20 ticks of fees

    Returns:
        Dict with:
        - color: 'green', 'amber', or 'red'
        - tick_countdown: estimated ticks remaining before exhaustion (int or None if no fees)
        - aggregate_fee: total per-tick fee across all active positions
    """
    db = get_db()

    # Get user balance
    user_row = db.execute(
        "SELECT balance FROM users WHERE id = ?", (user_id,)
    ).fetchone()
    if user_row is None:
        return {'color': 'green', 'tick_countdown': None, 'aggregate_fee': 0.0}

    user_balance = user_row['balance']

    # Get all active short positions with ore data
    positions = db.execute(
        """SELECT sp.share_quantity, o.current_price, o.volatility
           FROM short_positions sp
           JOIN ores o ON sp.ore_id = o.id
           WHERE sp.user_id = ? AND sp.status = 'active'""",
        (user_id,)
    ).fetchall()

    if not positions:
        return {'color': 'green', 'tick_countdown': None, 'aggregate_fee': 0.0}

    ticks_per_hour = _get_ticks_per_hour()

    # Sum up per-tick fees across all active positions
    aggregate_fee = 0.0
    for pos in positions:
        short_value = pos['share_quantity'] * pos['current_price']
        tick_fee = _calculate_tick_fee(short_value, pos['volatility'], ticks_per_hour)
        aggregate_fee += tick_fee

    aggregate_fee = round(aggregate_fee, 2)

    # Calculate tick countdown
    if aggregate_fee <= 0:
        tick_countdown = None
        color = 'green'
    else:
        tick_countdown = int(user_balance / aggregate_fee) if user_balance > 0 else 0

        if tick_countdown > 60:
            color = 'green'
        elif tick_countdown >= 20:
            color = 'amber'
        else:
            color = 'red'

    return {
        'color': color,
        'tick_countdown': tick_countdown,
        'aggregate_fee': aggregate_fee,
    }


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

    # Short position data (only for advanced mode users)
    short_position_cards = []
    threat_horizon = None
    advanced_active = is_advanced_active(current_user.id)
    shorts_summary = None

    if advanced_active:
        short_position_cards = _get_short_position_cards(current_user.id)
        if short_position_cards:
            threat_horizon = _get_threat_horizon_data(current_user.id)
            # Compute aggregate shorts summary for dashboard
            total_short_value = sum(c['short_value'] for c in short_position_cards)
            total_short_pnl = sum(c['unrealized_pnl'] for c in short_position_cards)
            shorts_summary = {
                'total_short_value': round(total_short_value, 2),
                'unrealized_pnl': round(total_short_pnl, 2),
                'num_positions': len(short_position_cards),
            }

    # Net worth (includes short equity for advanced users)
    from app.models import get_net_worth
    net_worth = get_net_worth(current_user.id)

    # Longs summary
    longs_summary = {
        'holdings_value': round(portfolio_value, 2),
        'unrealized_pnl': round(profit_loss, 2),
        'num_positions': len(holdings) if holdings else 0,
    }

    # Total P/L combines longs and shorts
    total_pnl = profit_loss + (shorts_summary['unrealized_pnl'] if shorts_summary else 0)

    template_ctx = dict(
        user=user,
        holdings=holdings,
        portfolio_value=portfolio_value,
        total_value=total_value,
        profit_loss=profit_loss,
        total_pnl=round(total_pnl, 2),
        net_worth=round(net_worth, 2),
        top_movers=top_movers,
        recent_transactions=recent_transactions,
        short_position_cards=short_position_cards,
        threat_horizon=threat_horizon,
        advanced_active=advanced_active,
        longs_summary=longs_summary,
        shorts_summary=shorts_summary,
    )

    # HTMX partial: return only the dynamic sections
    if request.headers.get('HX-Request'):
        # Check which section is requesting the update
        hx_target = request.headers.get('HX-Target', '')
        if hx_target == 'short-positions-section':
            # Short position cards refresh (legacy, will be removed later)
            return render_template('partials/short_position_cards.html',
                                   short_position_cards=short_position_cards,
                                   threat_horizon=threat_horizon)
        # Default: dashboard live stats refresh
        return render_template('partials/dashboard_live.html', **template_ctx)

    return render_template('pages/dashboard.html', **template_ctx)
