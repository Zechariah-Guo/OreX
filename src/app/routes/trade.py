"""Trade routes: buy and sell ores."""

from flask import Blueprint, render_template, redirect, url_for, flash, request, current_app, abort
from flask_login import login_required, current_user

from app.database import get_db
from app.models import (
    get_ore_by_id, get_user_by_id, get_holding,
    create_holding, update_holding, delete_holding,
    create_transaction
)
from app.market.influence import record_player_trade
from app.utils.validation import validate_quantity
from app.advanced import is_advanced_active
from app.decorators import advanced_required

trade_bp = Blueprint('trade', __name__)


def _get_buy_cap():
    """Get the buy quantity cap for the current user.

    Returns None if advanced mode is active (no cap), otherwise returns
    the MAX_BUY_QUANTITY config value for standard mode players.
    """
    if current_user.is_authenticated and is_advanced_active(current_user.id):
        return None
    return current_app.config.get('MAX_BUY_QUANTITY', 500)


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
        buy_cap = _get_buy_cap()

        if confirmed:
            # Execute the trade
            quantity_str = request.form.get('quantity')
            quantity, error = validate_quantity(quantity_str, max_quantity=buy_cap)
            if error:
                flash(error, 'error')
                return redirect(url_for('market.ore_detail', ore_id=ore_id))

            # Re-fetch current price (may have changed since confirmation page)
            ore = get_ore_by_id(ore_id)
            total_cost = quantity * ore['current_price']

            # Process optional stop_loss and take_profit parameters
            stop_loss = None
            take_profit = None
            advanced_active = is_advanced_active(current_user.id)

            if advanced_active:
                stop_loss_str = request.form.get('stop_loss')
                take_profit_str = request.form.get('take_profit')

                if stop_loss_str:
                    try:
                        stop_loss = float(stop_loss_str)
                    except (ValueError, TypeError):
                        flash('Stop loss must be a valid number.', 'error')
                        user = get_user_by_id(current_user.id)
                        return render_template('pages/trade_confirm.html',
                                               ore=ore, quantity=quantity, price=ore['current_price'],
                                               total=total_cost, trade_type='buy',
                                               balance_after=user.balance - total_cost)
                    if stop_loss >= ore['current_price']:
                        flash(f'Stop loss must be below current price (${ore["current_price"]:,.2f}).', 'error')
                        user = get_user_by_id(current_user.id)
                        return render_template('pages/trade_confirm.html',
                                               ore=ore, quantity=quantity, price=ore['current_price'],
                                               total=total_cost, trade_type='buy',
                                               balance_after=user.balance - total_cost)

                if take_profit_str:
                    try:
                        take_profit = float(take_profit_str)
                    except (ValueError, TypeError):
                        flash('Take profit must be a valid number.', 'error')
                        user = get_user_by_id(current_user.id)
                        return render_template('pages/trade_confirm.html',
                                               ore=ore, quantity=quantity, price=ore['current_price'],
                                               total=total_cost, trade_type='buy',
                                               balance_after=user.balance - total_cost)
                    if take_profit <= ore['current_price']:
                        flash(f'Take profit must be above current price (${ore["current_price"]:,.2f}).', 'error')
                        user = get_user_by_id(current_user.id)
                        return render_template('pages/trade_confirm.html',
                                               ore=ore, quantity=quantity, price=ore['current_price'],
                                               total=total_cost, trade_type='buy',
                                               balance_after=user.balance - total_cost)

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
                    holding_id = holding['id']
                else:
                    create_holding(user.id, ore_id, quantity, ore['current_price'])
                    # Get the newly created holding ID
                    new_holding = get_holding(user.id, ore_id)
                    holding_id = new_holding['id']

                # Record transaction
                create_transaction(user.id, ore_id, 'buy', quantity, ore['current_price'], total_cost)

                # Insert stop_loss/take_profit order if advanced mode is active and values provided
                if advanced_active and (stop_loss is not None or take_profit is not None):
                    db.execute(
                        """INSERT INTO stop_loss_take_profit (holding_id, stop_loss, take_profit, active)
                           VALUES (?, ?, ?, 1)""",
                        (holding_id, stop_loss, take_profit)
                    )

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
            quantity, error = validate_quantity(quantity_str, max_quantity=buy_cap)
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


@trade_bp.route('/trade/sltp/<int:holding_id>', methods=['POST'])
@login_required
@advanced_required
def modify_sltp(holding_id):
    """Modify or remove stop loss / take profit on an existing holding."""
    db = get_db()

    # Fetch holding and verify ownership
    holding = db.execute(
        "SELECT * FROM holdings WHERE id = ?", (holding_id,)
    ).fetchone()

    if not holding or holding['user_id'] != current_user.id:
        abort(403)

    # Get current ore price for validation
    ore = get_ore_by_id(holding['ore_id'])
    if not ore:
        flash('Ore not found.', 'error')
        return redirect(url_for('portfolio.overview'))

    current_price = ore['current_price']

    # Parse optional stop_loss and take_profit form values
    stop_loss_str = request.form.get('stop_loss', '').strip()
    take_profit_str = request.form.get('take_profit', '').strip()

    stop_loss = None
    take_profit = None

    # Validate stop_loss if provided
    if stop_loss_str:
        try:
            stop_loss = float(stop_loss_str)
        except (ValueError, TypeError):
            flash('Stop loss must be a valid number.', 'error')
            return redirect(url_for('market.ore_detail', ore_id=holding['ore_id']))
        if stop_loss >= current_price:
            flash(f'Stop loss must be below current price (${current_price:,.2f}).', 'error')
            return redirect(url_for('market.ore_detail', ore_id=holding['ore_id']))

    # Validate take_profit if provided
    if take_profit_str:
        try:
            take_profit = float(take_profit_str)
        except (ValueError, TypeError):
            flash('Take profit must be a valid number.', 'error')
            return redirect(url_for('market.ore_detail', ore_id=holding['ore_id']))
        if take_profit <= current_price:
            flash(f'Take profit must be above current price (${current_price:,.2f}).', 'error')
            return redirect(url_for('market.ore_detail', ore_id=holding['ore_id']))

    # Check if an existing SL/TP order exists for this holding
    existing = db.execute(
        "SELECT * FROM stop_loss_take_profit WHERE holding_id = ? AND active = 1",
        (holding_id,)
    ).fetchone()

    if stop_loss is None and take_profit is None:
        # Both empty — deactivate any existing SL/TP order
        if existing:
            db.execute(
                "UPDATE stop_loss_take_profit SET active = 0 WHERE id = ?",
                (existing['id'],)
            )
            db.commit()
            flash('Stop loss and take profit removed.', 'success')
        else:
            flash('No active stop loss or take profit to remove.', 'info')
    else:
        # Update existing or create new SL/TP order
        if existing:
            db.execute(
                "UPDATE stop_loss_take_profit SET stop_loss = ?, take_profit = ?, active = 1 WHERE id = ?",
                (stop_loss, take_profit, existing['id'])
            )
        else:
            db.execute(
                """INSERT INTO stop_loss_take_profit (holding_id, stop_loss, take_profit, active)
                   VALUES (?, ?, ?, 1)""",
                (holding_id, stop_loss, take_profit)
            )
        db.commit()
        flash('Stop loss and take profit updated.', 'success')

    return redirect(url_for('portfolio.overview'))
