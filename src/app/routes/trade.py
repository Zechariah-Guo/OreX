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
from app.market.shorting import (
    _calculate_short_ratio,
    _calculate_collateral_multiplier,
    _calculate_total_locked_collateral,
    _calculate_player_margin,
    _calculate_tick_fee,
    _calculate_squeeze_price,
    _get_ticks_per_hour,
    _close_position,
)
from app.utils.validation import validate_quantity
from app.advanced import is_advanced_active
from app.decorators import advanced_required
from app.config import Config

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


@trade_bp.route('/trade/short/open/<int:ore_id>', methods=['POST'])
@login_required
@advanced_required
def short_open(ore_id):
    """Open a new short position — show confirmation or execute."""
    # Look up ore and validate it exists with a positive price
    ore = get_ore_by_id(ore_id)
    if not ore:
        flash('Ore not found.', 'error')
        return redirect(url_for('market.overview'))

    current_price = ore['current_price']
    if current_price <= 0:
        flash('Cannot short an ore with zero market price.', 'error')
        return redirect(url_for('market.ore_detail', ore_id=ore_id))

    # Validate share quantity
    quantity_str = request.form.get('quantity', '')
    try:
        quantity = int(quantity_str)
    except (ValueError, TypeError):
        flash('Share quantity must be a whole number.', 'error')
        return redirect(url_for('market.ore_detail', ore_id=ore_id))

    if quantity < Config.SHORT_MIN_QUANTITY or quantity > Config.SHORT_MAX_QUANTITY:
        flash(f'Share quantity must be between {Config.SHORT_MIN_QUANTITY:,} and {Config.SHORT_MAX_QUANTITY:,}.', 'error')
        return redirect(url_for('market.ore_detail', ore_id=ore_id))

    # Calculate collateral requirements (Shorting_fixup.md Fix #2, #3)
    db = get_db()
    short_ratio = _calculate_short_ratio(db, ore_id)
    collateral_multiplier = _calculate_collateral_multiplier(short_ratio)
    locked_collateral = _calculate_total_locked_collateral(quantity, current_price, collateral_multiplier)
    player_margin = _calculate_player_margin(quantity, current_price, collateral_multiplier)

    # Check user balance against MARGIN (what they pay), not full vault
    user = get_user_by_id(current_user.id)
    if user.balance < player_margin:
        flash(
            f'Insufficient funds. You need ${player_margin:,.2f} margin but only have ${user.balance:,.2f} available.',
            'error'
        )
        return redirect(url_for('market.ore_detail', ore_id=ore_id))

    # Check if this is the confirmed execution step
    confirmed = request.form.get('confirmed')

    if not confirmed:
        # Show confirmation page with SL/TP fields
        ticks_per_hour = _get_ticks_per_hour()
        position_size = quantity * current_price
        short_value = position_size
        volatility = ore['volatility'] if ore['volatility'] else 0.5
        tick_fee = _calculate_tick_fee(short_value, volatility, ticks_per_hour)
        crowding_surcharge = (collateral_multiplier - Config.SHORT_BASE_REQUIREMENT) * 100

        # Estimate squeeze price (use margin as what's deducted, vault as locked)
        remaining_cash = user.balance - player_margin
        squeeze_price = _calculate_squeeze_price(
            {'share_quantity': quantity, 'locked_collateral': locked_collateral},
            remaining_cash, volatility, ticks_per_hour
        )

        return render_template('pages/short_confirm.html',
                               ore=ore,
                               quantity=quantity,
                               price=current_price,
                               position_size=position_size,
                               collateral=locked_collateral,
                               player_margin=player_margin,
                               crowding_surcharge=crowding_surcharge,
                               tick_fee=tick_fee,
                               squeeze_price=squeeze_price,
                               balance_after=user.balance - player_margin)

    # --- Confirmed: execute the short ---

    # Validate optional stop_loss and take_profit
    stop_loss = None
    take_profit = None

    stop_loss_str = request.form.get('stop_loss', '').strip()
    take_profit_str = request.form.get('take_profit', '').strip()

    if stop_loss_str:
        try:
            stop_loss = float(stop_loss_str)
        except (ValueError, TypeError):
            flash('Stop loss must be a valid number.', 'error')
            return redirect(url_for('market.ore_detail', ore_id=ore_id))
        if stop_loss <= current_price:
            flash(f'Stop loss must be above current price (${current_price:,.2f}).', 'error')
            return redirect(url_for('market.ore_detail', ore_id=ore_id))

    if take_profit_str:
        try:
            take_profit = float(take_profit_str)
        except (ValueError, TypeError):
            flash('Take profit must be a valid number.', 'error')
            return redirect(url_for('market.ore_detail', ore_id=ore_id))
        if take_profit >= current_price:
            flash(f'Take profit must be below current price (${current_price:,.2f}).', 'error')
            return redirect(url_for('market.ore_detail', ore_id=ore_id))

    # Execute the short open atomically
    try:
        # Deduct MARGIN (player's portion) from FreeCash — vault is larger (includes synthetic proceeds)
        new_balance = user.balance - player_margin
        db.execute("UPDATE users SET balance = ? WHERE id = ?", (new_balance, current_user.id))

        # Insert short position record
        db.execute(
            """INSERT INTO short_positions
               (user_id, ore_id, share_quantity, entry_price, locked_collateral,
                stop_loss_price, take_profit_price)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (current_user.id, ore_id, quantity, current_price, locked_collateral,
             stop_loss, take_profit)
        )

        # Record transaction
        create_transaction(
            current_user.id, ore_id, 'short_open',
            quantity, current_price, locked_collateral
        )

        db.commit()

        # Register sell-type influence for market algorithm
        record_player_trade(ore_id, quantity, 'sell')

        flash(
            f'Successfully opened short position: {quantity} {ore["name"]} at ${current_price:,.2f}. '
            f'Margin deducted: ${player_margin:,.2f}. Vault locked: ${locked_collateral:,.2f}.',
            'success'
        )
        return redirect(url_for('portfolio.overview'))

    except Exception as e:
        db.rollback()
        flash('An error occurred while opening your short position. Please try again.', 'error')
        return redirect(url_for('market.ore_detail', ore_id=ore_id))


@trade_bp.route('/trade/short/close/<int:position_id>', methods=['POST'])
@login_required
@advanced_required
def short_close(position_id):
    """Voluntarily close an active short position."""
    db = get_db()

    # Look up the short position by ID
    position = db.execute(
        "SELECT * FROM short_positions WHERE id = ?", (position_id,)
    ).fetchone()

    if not position:
        abort(404)

    # Verify position belongs to current user
    if position['user_id'] != current_user.id:
        abort(403)

    # Verify position is active
    if position['status'] != 'active':
        flash('This position is not active and cannot be closed.', 'error')
        return redirect(url_for('portfolio.overview')), 400

    # Get current ore price
    ore = db.execute(
        "SELECT current_price, name FROM ores WHERE id = ?", (position['ore_id'],)
    ).fetchone()

    if not ore:
        flash('Ore not found.', 'error')
        return redirect(url_for('portfolio.overview'))

    current_price = ore['current_price']

    try:
        # Close the position via shared close logic
        _close_position(db, position, "voluntary", current_price)

        # Register buy-type influence for market algorithm
        record_player_trade(position['ore_id'], position['share_quantity'], 'buy')

        db.commit()

        # Calculate true P/L for flash message (price movement minus fees)
        entry_value = position['share_quantity'] * position['entry_price']
        short_value = position['share_quantity'] * current_price
        gross_pnl = entry_value - short_value
        net_pnl = gross_pnl - position['cumulative_fees_paid']

        if net_pnl >= 0:
            flash(
                f'Successfully closed short position on {ore["name"]}. Net profit: ${net_pnl:,.2f}!',
                'success'
            )
        else:
            flash(
                f'Closed short position on {ore["name"]}. Net loss: ${abs(net_pnl):,.2f}.',
                'warning'
            )

        return redirect(url_for('portfolio.overview'))

    except Exception as e:
        db.rollback()
        flash('An error occurred while closing your short position. Please try again.', 'error')
        return redirect(url_for('portfolio.overview'))


@trade_bp.route('/trade/short/preview', methods=['POST'])
@login_required
@advanced_required
def short_preview():
    """htmx endpoint: returns partial HTML with short position cost breakdown."""
    ore_id_str = request.form.get('ore_id', '')
    quantity_str = request.form.get('quantity', '')

    # Parse ore_id
    try:
        ore_id = int(ore_id_str)
    except (ValueError, TypeError):
        return render_template('partials/short_preview.html',
                               position_size=0,
                               collateral=0,
                               crowding_surcharge=0,
                               tick_fee=0,
                               squeeze_price=0,
                               insufficient=False,
                               quantity_zero=True)

    # Parse quantity — treat 0, empty, or invalid as zeroed preview
    try:
        quantity = int(quantity_str)
    except (ValueError, TypeError):
        quantity = 0

    if quantity <= 0:
        return render_template('partials/short_preview.html',
                               position_size=0,
                               collateral=0,
                               crowding_surcharge=0,
                               tick_fee=0,
                               squeeze_price=0,
                               insufficient=False,
                               quantity_zero=True)

    # Look up ore
    ore = get_ore_by_id(ore_id)
    if not ore:
        return render_template('partials/short_preview.html',
                               position_size=0,
                               collateral=0,
                               crowding_surcharge=0,
                               tick_fee=0,
                               squeeze_price=0,
                               insufficient=False,
                               quantity_zero=True)

    current_price = ore['current_price']
    volatility = ore['volatility']

    # Calculate position metrics
    db = get_db()
    short_ratio = _calculate_short_ratio(db, ore_id)
    multiplier = _calculate_collateral_multiplier(short_ratio)
    position_size = round(quantity * current_price, 2)
    collateral = _calculate_total_locked_collateral(quantity, current_price, multiplier)
    player_margin = _calculate_player_margin(quantity, current_price, multiplier)

    # Crowding Surcharge % = (multiplier - BASE_REQUIREMENT) * 100
    crowding_surcharge = round((multiplier - Config.SHORT_BASE_REQUIREMENT) * 100, 1)

    # Tick fee calculation
    ticks_per_hour = _get_ticks_per_hour()
    tick_fee = _calculate_tick_fee(position_size, volatility, ticks_per_hour)

    # Squeeze price estimation (use margin as deducted, vault as locked)
    user = get_user_by_id(current_user.id)
    preview_position = {
        'share_quantity': quantity,
        'entry_price': current_price,
        'locked_collateral': collateral,
    }
    squeeze_price = _calculate_squeeze_price(
        preview_position, user.balance - player_margin, volatility, ticks_per_hour
    )
    # Convert infinity to None for template rendering
    if squeeze_price == float('inf'):
        squeeze_price = None

    # Check if MARGIN exceeds FreeCash (player only pays margin, not full vault)
    insufficient = player_margin > user.balance

    return render_template('partials/short_preview.html',
                           position_size=position_size,
                           collateral=collateral,
                           player_margin=player_margin,
                           crowding_surcharge=crowding_surcharge,
                           tick_fee=tick_fee,
                           squeeze_price=squeeze_price,
                           insufficient=insufficient,
                           user_balance=user.balance,
                           quantity_zero=False)


@trade_bp.route('/trade/short/edit/<int:position_id>', methods=['POST'])
@login_required
@advanced_required
def short_edit_sltp(position_id):
    """Update SL/TP values on an existing short position."""
    db = get_db()

    # Look up the short position
    position = db.execute(
        "SELECT * FROM short_positions WHERE id = ?", (position_id,)
    ).fetchone()

    if not position:
        abort(404)

    # Verify ownership
    if position['user_id'] != current_user.id:
        abort(403)

    # Verify position is active
    if position['status'] != 'active':
        flash('This position is not active and cannot be edited.', 'error')
        return redirect(url_for('portfolio.overview'))

    # Get current ore price for validation
    ore = get_ore_by_id(position['ore_id'])
    if not ore:
        flash('Ore not found.', 'error')
        return redirect(url_for('portfolio.overview'))

    current_price = ore['current_price']

    # Parse form data (empty string or None means clear/remove the trigger)
    stop_loss_str = request.form.get('stop_loss', '').strip()
    take_profit_str = request.form.get('take_profit', '').strip()

    stop_loss = None
    take_profit = None

    # Validate stop_loss if provided (for shorts, SL must be ABOVE current price)
    if stop_loss_str:
        try:
            stop_loss = float(stop_loss_str)
        except (ValueError, TypeError):
            flash('Stop loss must be a valid number.', 'error')
            return redirect(url_for('portfolio.overview'))
        if stop_loss <= current_price:
            flash(f'Stop loss must be above current price (${current_price:,.2f}).', 'error')
            return redirect(url_for('portfolio.overview'))

    # Validate take_profit if provided (for shorts, TP must be BELOW current price)
    if take_profit_str:
        try:
            take_profit = float(take_profit_str)
        except (ValueError, TypeError):
            flash('Take profit must be a valid number.', 'error')
            return redirect(url_for('portfolio.overview'))
        if take_profit >= current_price:
            flash(f'Take profit must be below current price (${current_price:,.2f}).', 'error')
            return redirect(url_for('portfolio.overview'))

    # Update the short position SL/TP values (None sets to NULL in DB)
    db.execute(
        "UPDATE short_positions SET stop_loss_price = ?, take_profit_price = ? WHERE id = ?",
        (stop_loss, take_profit, position_id)
    )
    db.commit()

    flash('Stop loss and take profit updated.', 'success')
    return redirect(url_for('portfolio.overview'))
