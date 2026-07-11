"""Trade routes: buy and sell ores."""

from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user

from app.database import get_db
from app.models import (
    get_ore_by_id, get_user_by_id, get_holding,
    create_holding, update_holding, delete_holding,
    create_transaction
)
from app.market.influence import record_player_trade
from app.utils.validation import validate_quantity

trade_bp = Blueprint('trade', __name__)


@trade_bp.route('/trade/buy/<int:ore_id>', methods=['GET', 'POST'])
@login_required
def buy(ore_id):
    """Buy ore: show confirmation or execute the trade."""
    ore = get_ore_by_id(ore_id)
    if not ore:
        flash('Ore not found.', 'error')
        return redirect(url_for('market.overview'))

    if request.method == 'POST':
        # Check if this is the confirmation step
        confirmed = request.form.get('confirmed')

        if confirmed:
            # Execute the trade
            quantity_str = request.form.get('quantity')
            quantity, error = validate_quantity(quantity_str)
            if error:
                flash(error, 'error')
                return redirect(url_for('market.ore_detail', ore_id=ore_id))

            # Re-fetch current price (may have changed since confirmation page)
            ore = get_ore_by_id(ore_id)
            total_cost = quantity * ore['current_price']

            # Check balance
            user = get_user_by_id(current_user.id)
            if user.balance < total_cost:
                flash('Insufficient funds for this trade.', 'error')
                return redirect(url_for('market.ore_detail', ore_id=ore_id))

            # Execute atomically
            db = get_db()
            try:
                # Deduct balance
                new_balance = user.balance - total_cost
                db.execute("UPDATE users SET balance = ? WHERE id = ?", (new_balance, user.id))

                # Update or create holding
                holding = get_holding(user.id, ore_id)
                if holding:
                    # Weighted average price
                    old_qty = holding['quantity']
                    old_avg = holding['avg_purchase_price']
                    new_qty = old_qty + quantity
                    new_avg = ((old_qty * old_avg) + (quantity * ore['current_price'])) / new_qty
                    update_holding(holding['id'], new_qty, new_avg)
                else:
                    create_holding(user.id, ore_id, quantity, ore['current_price'])

                # Record transaction
                create_transaction(user.id, ore_id, 'buy', quantity, ore['current_price'], total_cost)

                db.commit()
                flash(f'Successfully bought {quantity} {ore["name"]} for ${total_cost:,.2f}!', 'success')

                # Record trade for market influence on next tick
                record_player_trade(ore_id, quantity, 'buy')

                return redirect(url_for('portfolio.overview'))

            except Exception as e:
                db.rollback()
                flash('An error occurred while processing your trade. Please try again.', 'error')
                return redirect(url_for('market.ore_detail', ore_id=ore_id))

        else:
            # Show confirmation page
            quantity_str = request.form.get('quantity')
            quantity, error = validate_quantity(quantity_str)
            if error:
                flash(error, 'error')
                return redirect(url_for('market.ore_detail', ore_id=ore_id))

            total_cost = quantity * ore['current_price']

            # Check balance before showing confirmation
            user = get_user_by_id(current_user.id)
            if user.balance < total_cost:
                flash('Insufficient funds for this trade.', 'error')
                return redirect(url_for('market.ore_detail', ore_id=ore_id))

            return render_template('pages/trade_confirm.html',
                                   ore=ore,
                                   quantity=quantity,
                                   price=ore['current_price'],
                                   total=total_cost,
                                   trade_type='buy',
                                   balance_after=user.balance - total_cost)

    return redirect(url_for('market.ore_detail', ore_id=ore_id))


@trade_bp.route('/trade/sell/<int:ore_id>', methods=['GET', 'POST'])
@login_required
def sell(ore_id):
    """Sell ore: show confirmation or execute the trade."""
    ore = get_ore_by_id(ore_id)
    if not ore:
        flash('Ore not found.', 'error')
        return redirect(url_for('market.overview'))

    if request.method == 'POST':
        confirmed = request.form.get('confirmed')

        if confirmed:
            # Execute the trade
            quantity_str = request.form.get('quantity')
            quantity, error = validate_quantity(quantity_str)
            if error:
                flash(error, 'error')
                return redirect(url_for('market.ore_detail', ore_id=ore_id))

            # Check holding
            holding = get_holding(current_user.id, ore_id)
            if not holding or holding['quantity'] < quantity:
                flash('You do not have enough of this ore to sell.', 'error')
                return redirect(url_for('market.ore_detail', ore_id=ore_id))

            # Re-fetch current price
            ore = get_ore_by_id(ore_id)
            total_proceeds = quantity * ore['current_price']

            # Execute atomically
            db = get_db()
            try:
                # Credit balance
                user = get_user_by_id(current_user.id)
                new_balance = user.balance + total_proceeds
                db.execute("UPDATE users SET balance = ? WHERE id = ?", (new_balance, current_user.id))

                # Update or delete holding
                if holding['quantity'] == quantity:
                    delete_holding(holding['id'])
                else:
                    new_qty = holding['quantity'] - quantity
                    update_holding(holding['id'], new_qty, holding['avg_purchase_price'])

                # Record transaction
                create_transaction(current_user.id, ore_id, 'sell', quantity, ore['current_price'], total_proceeds)

                db.commit()
                flash(f'Successfully sold {quantity} {ore["name"]} for ${total_proceeds:,.2f}!', 'success')

                # Record trade for market influence on next tick
                record_player_trade(ore_id, quantity, 'sell')

                return redirect(url_for('portfolio.overview'))

            except Exception as e:
                db.rollback()
                flash('An error occurred while processing your trade. Please try again.', 'error')
                return redirect(url_for('market.ore_detail', ore_id=ore_id))

        else:
            # Show confirmation page
            quantity_str = request.form.get('quantity')
            quantity, error = validate_quantity(quantity_str)
            if error:
                flash(error, 'error')
                return redirect(url_for('market.ore_detail', ore_id=ore_id))

            # Check holding
            holding = get_holding(current_user.id, ore_id)
            if not holding or holding['quantity'] < quantity:
                flash('You do not have enough of this ore to sell.', 'error')
                return redirect(url_for('market.ore_detail', ore_id=ore_id))

            total_proceeds = quantity * ore['current_price']
            user = get_user_by_id(current_user.id)

            return render_template('pages/trade_confirm.html',
                                   ore=ore,
                                   quantity=quantity,
                                   price=ore['current_price'],
                                   total=total_proceeds,
                                   trade_type='sell',
                                   balance_after=user.balance + total_proceeds)

    return redirect(url_for('market.ore_detail', ore_id=ore_id))
