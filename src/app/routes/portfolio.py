"""Portfolio routes: view user holdings."""

import json

from flask import Blueprint, render_template, request
from flask_login import login_required, current_user

from app.database import get_db
from app.models import get_holdings_by_user, get_user_by_id
from app.advanced import is_advanced_active
from app.market.shorting import (
    _calculate_tick_fee,
    _calculate_squeeze_price,
    _get_ticks_per_hour,
)

portfolio_bp = Blueprint('portfolio', __name__)


def _get_short_positions(user_id: int) -> list:
    """Build display data for each active short position."""
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

    user_row = db.execute(
        "SELECT balance FROM users WHERE id = ?", (user_id,)
    ).fetchone()
    user_balance = user_row['balance'] if user_row else 0.0

    ticks_per_hour = _get_ticks_per_hour()
    results = []

    for pos in positions:
        shares = pos['share_quantity']
        current_price = pos['current_price']
        entry_price = pos['entry_price']
        volatility = pos['volatility']

        unrealized_pnl = (entry_price * shares) - (current_price * shares)

        tick_fee = _calculate_tick_fee(shares * current_price, volatility, ticks_per_hour)

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
        # Convert infinity to None for template rendering
        if squeeze_price == float('inf'):
            squeeze_price = None

        results.append({
            'id': pos['id'],
            'ore_name': pos['ore_name'],
            'ore_id': pos['ore_id'],
            'share_quantity': shares,
            'entry_price': entry_price,
            'current_price': current_price,
            'unrealized_pnl': round(unrealized_pnl, 2),
            'cumulative_fees_paid': round(pos['cumulative_fees_paid'], 2),
            'squeeze_price': squeeze_price,
            'stop_loss': pos['stop_loss_price'],
            'take_profit': pos['take_profit_price'],
        })

    return results


@portfolio_bp.route('/portfolio')
@login_required
def overview():
    """Display the user's portfolio with holdings and profit/loss."""
    user = get_user_by_id(current_user.id)
    holdings = get_holdings_by_user(current_user.id)

    # Fetch active SL/TP orders for this user's holdings if advanced mode is active
    sltp_by_holding = {}
    advanced_active = is_advanced_active(current_user.id)

    short_positions = []
    if advanced_active:
        db = get_db()
        holding_ids = [h['id'] for h in holdings]
        if holding_ids:
            placeholders = ','.join('?' * len(holding_ids))
            sltp_rows = db.execute(
                f"SELECT * FROM stop_loss_take_profit WHERE holding_id IN ({placeholders}) AND active = 1",
                holding_ids
            ).fetchall()
            for row in sltp_rows:
                sltp_by_holding[row['holding_id']] = {
                    'stop_loss': row['stop_loss'],
                    'take_profit': row['take_profit'],
                }

        # Fetch active short positions
        short_positions = _get_short_positions(current_user.id)

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

        holding_entry = {
            'id': h['id'],
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
        }

        # Attach SL/TP data if available
        if h['id'] in sltp_by_holding:
            holding_entry['sltp'] = sltp_by_holding[h['id']]
        else:
            holding_entry['sltp'] = None

        holdings_data.append(holding_entry)

    total_profit_loss = total_current_value - total_invested
    total_portfolio_value = user.balance + total_current_value

    # HTMX partial: return only the live content
    if request.headers.get('HX-Request'):
        return render_template('partials/portfolio_live.html',
                               user=user,
                               holdings=holdings_data,
                               short_positions=short_positions,
                               is_advanced_active=advanced_active,
                               total_current_value=total_current_value,
                               total_profit_loss=total_profit_loss,
                               total_portfolio_value=total_portfolio_value)

    return render_template('pages/portfolio.html',
                           user=user,
                           holdings=holdings_data,
                           short_positions=short_positions,
                           is_advanced_active=advanced_active,
                           total_invested=total_invested,
                           total_current_value=total_current_value,
                           total_profit_loss=total_profit_loss,
                           total_portfolio_value=total_portfolio_value)
