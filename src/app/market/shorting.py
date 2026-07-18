"""Shorting engine — collateral calculations and tick processing for short positions.

This module implements the core mechanics of the shorting system:
- Short ratio calculation (crowding metric per ore)
- Collateral multiplier with cubic penalty curve
- Total locked collateral computation
"""

import logging
from datetime import datetime

from app.config import Config
from app.models import (
    TRANSACTION_TYPE_SHORT_CLOSE,
    TRANSACTION_TYPE_SHORT_LIQUIDATED,
)

logger = logging.getLogger(__name__)


def _calculate_short_ratio(db, ore_id: int) -> float:
    """Compute global Short_Ratio for an ore.

    Short_Ratio = active_shorts / (active_shorts + longs)
    Returns 0.0 if no positions exist (both shorts and longs are zero).

    Args:
        db: An active sqlite3 connection.
        ore_id: The ore identifier to calculate the ratio for.

    Returns:
        A float between 0.0 and 1.0 representing the short crowding ratio.
    """
    # Count active short positions for this ore
    shorts = db.execute(
        "SELECT COUNT(*) FROM short_positions WHERE ore_id = ? AND status = 'active'",
        (ore_id,)
    ).fetchone()[0]

    # Count long holders for this ore (each holding row = one long position)
    longs = db.execute(
        "SELECT COUNT(*) FROM holdings WHERE ore_id = ?",
        (ore_id,)
    ).fetchone()[0]

    total = shorts + longs
    if total == 0:
        return 0.0

    return shorts / total


def _calculate_collateral_multiplier(short_ratio: float) -> float:
    """Calculate the collateral multiplier based on the short crowding ratio.

    Multiplier = BASE_REQUIREMENT + MAX_PENALTY * short_ratio^STEEPNESS
    The result is clamped to [0.50, 2.50] as a safety bound.

    The cubic exponent creates a "hockey stick" curve — negligible penalty for
    lightly-shorted ores, punishing for crowded ones.

    Args:
        short_ratio: A float between 0.0 and 1.0 from _calculate_short_ratio.

    Returns:
        A float representing the collateral multiplier, clamped to [0.50, 2.50].
    """
    multiplier = (
        Config.SHORT_BASE_REQUIREMENT
        + Config.SHORT_MAX_PENALTY * (short_ratio ** Config.SHORT_STEEPNESS)
    )
    return max(0.50, min(2.50, multiplier))


def _calculate_total_locked_collateral(shares: int, price: float, collateral_multiplier: float) -> float:
    """Compute the Total_Locked_Collateral (vault) for a short position.

    The vault holds BOTH the synthetic short sale proceeds AND the player's margin:
    Total_Locked_Collateral = Short_Value × (1 + Collateral_Multiplier)

    This matches the original plan: "The system locks $50,200 of the player's cash
    alongside the $100,000 short sale proceeds. Total frozen vault cash = $150,200."

    Args:
        shares: Number of shares being shorted (1-10,000).
        price: Current ore price at time of order.
        collateral_multiplier: The multiplier from _calculate_collateral_multiplier.

    Returns:
        The total vault amount (proceeds + margin), rounded to 2 decimal places.
    """
    short_value = shares * price
    return round(short_value * (1 + collateral_multiplier), 2)


def _calculate_player_margin(shares: int, price: float, collateral_multiplier: float) -> float:
    """Compute what the player actually pays from FreeCash to open a short.

    Player_Margin = Short_Value × Collateral_Multiplier

    This is the player's "skin in the game" — the margin portion. The rest of
    the vault (Short_Value) is synthetic proceeds the game adds.

    Args:
        shares: Number of shares being shorted (1-10,000).
        price: Current ore price at time of order.
        collateral_multiplier: The multiplier from _calculate_collateral_multiplier.

    Returns:
        The margin amount deducted from FreeCash, rounded to 2 decimal places.
    """
    short_value = shares * price
    return round(short_value * collateral_multiplier, 2)


def _get_ticks_per_hour() -> float:
    """Derive ticks per hour from Config.TICK_INTERVAL.

    Returns:
        Number of ticks that occur in one hour (3600 / TICK_INTERVAL).
    """
    return 3600 / Config.TICK_INTERVAL


def _calculate_tick_fee(short_value: float, volatility: float, ticks_per_hour: float) -> float:
    """Calculate the per-tick time-bleed fee for a short position.

    Tick_Fee = Short_Value * ((BASE_HOURLY_RATE + MAX_HOURLY_FEE * volatility^2) / ticks_per_hour)

    Args:
        short_value: Current value of the short position (shares × current_price).
        volatility: Ore volatility (0.0 to 1.5 scale).
        ticks_per_hour: Number of ticks per hour (derived from Config.TICK_INTERVAL).

    Returns:
        The tick fee amount, rounded to 2 decimal places.
    """
    hourly_rate = Config.SHORT_BASE_HOURLY_RATE + Config.SHORT_MAX_HOURLY_FEE * (volatility ** 2)
    tick_fee = short_value * (hourly_rate / ticks_per_hour)
    return round(tick_fee, 2)


def _calculate_squeeze_price(position, user_balance: float, volatility: float, ticks_per_hour: float) -> float:
    """Estimate the ore price at which FreeCash would be exhausted.

    Uses a conservative estimate based on base collateral multiplier (ignoring
    crowding penalty) to determine the price that would exhaust all available
    capital (FreeCash + locked collateral).

    Formula: P_sq ≈ (user_balance + locked_collateral) / (shares × BASE_REQUIREMENT)

    Args:
        position: A dict-like object with keys: share_quantity, entry_price, locked_collateral.
        user_balance: The player's current FreeCash (balance).
        volatility: Ore volatility (accepted for future fee-adjusted estimation).
        ticks_per_hour: Ticks per hour (accepted for future fee-adjusted estimation).

    Returns:
        The estimated squeeze price. Returns float('inf') for edge cases
        (zero shares, non-positive capital, non-positive result).
    """
    shares = position['share_quantity'] if isinstance(position, dict) else position.share_quantity
    locked = position['locked_collateral'] if isinstance(position, dict) else position.locked_collateral

    if shares <= 0:
        return float('inf')

    total_available = user_balance + locked
    if total_available <= 0:
        return float('inf')

    denominator = shares * Config.SHORT_BASE_REQUIREMENT
    if denominator <= 0:
        return float('inf')

    squeeze_price = total_available / denominator
    if squeeze_price <= 0:
        return float('inf')

    return round(squeeze_price, 2)


def _apply_time_bleed_fees(db, ores_map: dict, closed_ids: set):
    """Phase 3: Deduct per-tick fees from FreeCash. Oldest position first per user.

    For each active position (excluding those already closed in earlier phases),
    calculates the tick fee and deducts it from the user's FreeCash. Positions
    are processed per user in ascending opened_at order (oldest first).

    If a fee deduction would reduce FreeCash below zero, only the amount that
    brings FreeCash to exactly zero is deducted, the position is forcibly
    liquidated, and remaining positions for that user are skipped.

    Args:
        db: An active sqlite3 connection.
        ores_map: Dict of {ore_id: {'current_price': float, 'volatility': float, ...}}.
        closed_ids: Set of position IDs already closed in earlier phases.
                    Mutated in place to include positions closed by fee liquidation.
    """
    # Build exclusion placeholder for closed_ids
    if closed_ids:
        placeholders = ','.join('?' for _ in closed_ids)
        exclude_clause = f"AND sp.id NOT IN ({placeholders})"
        exclude_params = list(closed_ids)
    else:
        exclude_clause = ""
        exclude_params = []

    # Query active positions ordered by user_id, then opened_at ASC (oldest first)
    query = f"""
        SELECT sp.id, sp.user_id, sp.ore_id, sp.share_quantity,
               sp.entry_price, sp.locked_collateral, sp.cumulative_fees_paid,
               sp.opened_at
        FROM short_positions sp
        WHERE sp.status = 'active'
        {exclude_clause}
        ORDER BY sp.user_id ASC, sp.opened_at ASC
    """
    positions = db.execute(query, exclude_params).fetchall()

    if not positions:
        return

    ticks_per_hour = _get_ticks_per_hour()

    # Group positions by user_id (they're already ordered by user_id, opened_at)
    from itertools import groupby
    from operator import itemgetter

    # Convert rows to dicts for easier manipulation
    positions_list = [dict(row) for row in positions]

    for user_id, user_positions_iter in groupby(positions_list, key=itemgetter('user_id')):
        user_positions = list(user_positions_iter)

        # Get user's current balance
        user_row = db.execute(
            "SELECT balance FROM users WHERE id = ?", (user_id,)
        ).fetchone()
        if user_row is None:
            continue
        user_balance = user_row['balance']

        for pos in user_positions:
            ore_id = pos['ore_id']

            # Skip if ore not in ores_map (shouldn't happen, but defensive)
            if ore_id not in ores_map:
                continue

            current_price = ores_map[ore_id]['current_price']
            volatility = ores_map[ore_id]['volatility']

            # Calculate short value and tick fee
            short_value = pos['share_quantity'] * current_price
            tick_fee = _calculate_tick_fee(short_value, volatility, ticks_per_hour)

            if tick_fee <= 0:
                continue

            if tick_fee > user_balance:
                # Deduct only what's available to bring FreeCash to exactly 0
                partial_fee = user_balance
                user_balance = 0.0

                # Increment cumulative_fees_paid by the partial amount
                db.execute(
                    "UPDATE short_positions SET cumulative_fees_paid = cumulative_fees_paid + ? WHERE id = ?",
                    (partial_fee, pos['id'])
                )

                # Trigger forced liquidation for this position
                _close_position(db, pos, "forced_liquidation", current_price)
                closed_ids.add(pos['id'])

                # Break — skip remaining positions for this user
                break
            else:
                # Normal fee deduction
                user_balance -= tick_fee

                # Increment cumulative_fees_paid
                db.execute(
                    "UPDATE short_positions SET cumulative_fees_paid = cumulative_fees_paid + ? WHERE id = ?",
                    (tick_fee, pos['id'])
                )

        # Update user's balance
        db.execute(
            "UPDATE users SET balance = ? WHERE id = ?",
            (user_balance, user_id)
        )


def _close_position(db, position, close_type: str, current_price: float):
    """Shared close logic: calculate P/L, update status, record transaction, release collateral.

    Handles both profit (Short_Value <= Locked_Collateral) and loss
    (Short_Value > Locked_Collateral) scenarios.

    Args:
        db: An active sqlite3 connection.
        position: A sqlite3.Row or dict with keys: id, user_id, ore_id,
                  share_quantity, entry_price, locked_collateral, status.
        close_type: One of "voluntary", "sl_triggered", "tp_triggered",
                    "forced_liquidation".
        current_price: The ore's current market price at time of close.
    """
    # Extract position fields (support both dict and Row access)
    pos_id = position['id'] if isinstance(position, dict) else position['id']
    user_id = position['user_id'] if isinstance(position, dict) else position['user_id']
    ore_id = position['ore_id'] if isinstance(position, dict) else position['ore_id']
    shares = position['share_quantity'] if isinstance(position, dict) else position['share_quantity']
    locked_collateral = position['locked_collateral'] if isinstance(position, dict) else position['locked_collateral']

    # Calculate Short_Value (cost to buy back shares at current price)
    short_value = shares * current_price

    # Calculate P/L: positive means profit, negative means loss
    pnl = locked_collateral - short_value

    # Update player's FreeCash (balance)
    # Profit case: SV <= locked_collateral → credit (locked - SV) to FreeCash
    # Loss case: SV > locked_collateral → deduct (SV - locked) from FreeCash
    # In both cases, we add pnl (which is negative for losses)
    # Use MAX(0, ...) to prevent negative balance in edge cases
    db.execute(
        "UPDATE users SET balance = MAX(0, balance + ?) WHERE id = ?",
        (pnl, user_id)
    )

    # Update position status to 'closed' and set closed_at timestamp
    db.execute(
        "UPDATE short_positions SET status = 'closed', closed_at = datetime('now') WHERE id = ?",
        (pos_id,)
    )

    # Determine transaction type based on close_type
    if close_type == "forced_liquidation":
        trade_type = TRANSACTION_TYPE_SHORT_LIQUIDATED
    else:
        # voluntary, sl_triggered, tp_triggered all use short_close
        trade_type = TRANSACTION_TYPE_SHORT_CLOSE

    # Record the transaction with P/L as total_value
    _now = datetime.now().isoformat()
    db.execute(
        """INSERT INTO transactions (user_id, ore_id, type, quantity, price_at_trade, total_value, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (user_id, ore_id, trade_type, shares, current_price, pnl, _now)
    )


def _rebalance_margin(db, ores_map: dict, closed_ids: set):
    """Phase 2: Recalculate required collateral, transfer deficits or release surpluses.

    Processes positions grouped by user, largest Required_Collateral first.
    If a margin call deficit exceeds the user's FreeCash, all remaining FreeCash
    is transferred and forced liquidation is triggered for that position.

    Args:
        db: An active sqlite3 connection.
        ores_map: Dict of {ore_id: {'current_price': float, 'volatility': float, ...}}.
        closed_ids: Set of position IDs already closed in Phase 1 (SL/TP), to skip.
    """
    # Fetch all active positions not already closed this tick
    positions = db.execute(
        "SELECT * FROM short_positions WHERE status = 'active'"
    ).fetchall()

    # Filter out positions closed in Phase 1
    active_positions = [p for p in positions if p['id'] not in closed_ids]

    if not active_positions:
        return

    # Calculate Required_Collateral for each position and group by user
    # Each entry: (position_row, required_collateral)
    user_positions = {}
    for pos in active_positions:
        ore_id = pos['ore_id']
        if ore_id not in ores_map:
            continue

        current_price = ores_map[ore_id]['current_price']
        shares = pos['share_quantity']
        entry_price = pos['entry_price']

        # Derive the multiplier that was used at open time from stored data
        # At open: locked_collateral = entry_price × shares × (1 + multiplier)
        # So: multiplier = (locked_collateral / (entry_price × shares)) - 1
        # Then required at current price = current_price × shares × (1 + multiplier)
        # This avoids recalculating short_ratio (which changes as positions open/close)
        entry_value = entry_price * shares
        if entry_value > 0:
            open_factor = pos['locked_collateral'] / entry_value  # = (1 + multiplier_at_open)
        else:
            open_factor = 1.5  # fallback

        required_collateral = round(current_price * shares * open_factor, 2)

        user_id = pos['user_id']
        if user_id not in user_positions:
            user_positions[user_id] = []
        user_positions[user_id].append((pos, required_collateral))

    # Process each user's positions in descending Required_Collateral order
    for user_id, pos_list in user_positions.items():
        # Sort by Required_Collateral descending (largest first)
        pos_list.sort(key=lambda x: x[1], reverse=True)

        # Fetch current user balance
        user_row = db.execute(
            "SELECT balance FROM users WHERE id = ?", (user_id,)
        ).fetchone()
        if user_row is None:
            continue

        user_balance = user_row['balance']

        for pos, required_collateral in pos_list:
            locked_collateral = pos['locked_collateral']

            if required_collateral > locked_collateral:
                # Deficit: need to pull from FreeCash
                deficit = round(required_collateral - locked_collateral, 2)

                if deficit > user_balance:
                    # Cannot cover full deficit — transfer all remaining FreeCash,
                    # then trigger forced liquidation
                    new_locked = round(locked_collateral + user_balance, 2)

                    # Update locked collateral with whatever FreeCash we have
                    db.execute(
                        "UPDATE short_positions SET locked_collateral = ? WHERE id = ?",
                        (new_locked, pos['id'])
                    )

                    # Set user balance to 0
                    db.execute(
                        "UPDATE users SET balance = 0 WHERE id = ?",
                        (user_id,)
                    )
                    user_balance = 0.0

                    # Trigger forced liquidation for this position
                    # Re-fetch position with updated locked_collateral for _close_position
                    current_price = ores_map[pos['ore_id']]['current_price']
                    updated_pos = db.execute(
                        "SELECT * FROM short_positions WHERE id = ?", (pos['id'],)
                    ).fetchone()
                    _close_position(db, updated_pos, "forced_liquidation", current_price)

                    # Add to closed_ids so subsequent phases skip it
                    closed_ids.add(pos['id'])
                else:
                    # Can cover the full deficit
                    new_locked = round(locked_collateral + deficit, 2)

                    db.execute(
                        "UPDATE short_positions SET locked_collateral = ? WHERE id = ?",
                        (new_locked, pos['id'])
                    )

                    user_balance = round(user_balance - deficit, 2)
                    db.execute(
                        "UPDATE users SET balance = ? WHERE id = ?",
                        (user_balance, user_id)
                    )

            elif required_collateral < locked_collateral:
                # Per the original plan: vault only grows, never shrinks.
                # No surplus release — profit is realized at close time.
                # "The vault stays frozen until the position is resolved."
                pass
            # If required == locked, no action needed


def _evaluate_sltp_triggers(db, ores_map: dict) -> set:
    """Phase 1: Check SL/TP triggers. Returns set of position IDs closed this phase.

    Evaluates all active short positions that have a Stop Loss or Take Profit set.
    If the current ore price meets or exceeds the SL price, the position is closed
    as "sl_triggered". If the current ore price meets or falls below the TP price,
    the position is closed as "tp_triggered".

    This phase runs BEFORE margin calls and fees, so triggered positions do not
    incur time-bleed fees for that tick.

    Args:
        db: An active sqlite3 connection.
        ores_map: A dict of {ore_id: {'current_price': float, 'volatility': float, ...}}.

    Returns:
        A set of position IDs that were closed by SL/TP triggers this tick.
    """
    closed_ids = set()

    # Query active positions that have at least one of SL or TP set
    positions = db.execute(
        """SELECT * FROM short_positions
           WHERE status = 'active'
           AND (stop_loss_price IS NOT NULL OR take_profit_price IS NOT NULL)"""
    ).fetchall()

    for position in positions:
        ore_id = position['ore_id']

        # Skip if ore not in the current price map
        if ore_id not in ores_map:
            continue

        current_price = ores_map[ore_id]['current_price']
        stop_loss_price = position['stop_loss_price']
        take_profit_price = position['take_profit_price']

        # Check Stop Loss trigger: price rose to or above SL
        if stop_loss_price is not None and current_price >= stop_loss_price:
            _close_position(db, position, "sl_triggered", current_price)
            closed_ids.add(position['id'])
        # Check Take Profit trigger: price fell to or below TP
        elif take_profit_price is not None and current_price <= take_profit_price:
            _close_position(db, position, "tp_triggered", current_price)
            closed_ids.add(position['id'])

    return closed_ids


def _check_forced_liquidation(db, ores_map: dict, closed_ids: set):
    """Phase 4: Liquidate positions for users whose FreeCash is 0.

    After margin calls and fee deductions, any user with a balance of exactly 0
    and remaining active positions must have positions liquidated one at a time
    (highest Short_Value first) until FreeCash becomes positive.

    For each liquidated position:
    - _close_position handles buyback cost and credits max(0, locked - SV) to FreeCash
      (margin calls in Phase 2 should have ensured locked >= SV, so credit is non-negative)
    - A notification is created indicating the forced liquidation cause
    - The position is marked closed and added to closed_ids
    - Liquidation stops for a user once their FreeCash > 0

    Args:
        db: An active sqlite3 connection.
        ores_map: Dict of {ore_id: {'current_price': float, 'volatility': float, ...}}.
        closed_ids: Set of position IDs already closed in previous phases, to skip.
    """
    # Find users with balance == 0 who still have active positions (not in closed_ids)
    # We need to check each user individually since closed_ids is a Python-side filter
    users_at_zero = db.execute(
        "SELECT id FROM users WHERE balance = 0"
    ).fetchall()

    if not users_at_zero:
        return

    for user_row in users_at_zero:
        user_id = user_row['id']

        # Get this user's active positions that haven't been closed this tick
        positions = db.execute(
            "SELECT * FROM short_positions WHERE user_id = ? AND status = 'active'",
            (user_id,)
        ).fetchall()

        # Filter out positions already closed in earlier phases
        active_positions = [p for p in positions if p['id'] not in closed_ids]

        if not active_positions:
            continue

        # Calculate Short_Value for each position and sort by highest first
        position_sv_pairs = []
        for pos in active_positions:
            ore_id = pos['ore_id']
            if ore_id not in ores_map:
                continue
            current_price = ores_map[ore_id]['current_price']
            short_value = pos['share_quantity'] * current_price
            position_sv_pairs.append((pos, short_value, current_price))

        # Sort by Short_Value descending (highest first)
        position_sv_pairs.sort(key=lambda x: x[1], reverse=True)

        # Liquidate one at a time until FreeCash > 0
        for pos, short_value, current_price in position_sv_pairs:
            # Re-check user balance before each liquidation (it may have increased
            # from a previous liquidation's credit in this loop)
            user_balance_row = db.execute(
                "SELECT balance FROM users WHERE id = ?", (user_id,)
            ).fetchone()

            if user_balance_row is None:
                break

            user_balance = user_balance_row['balance']

            # Stop liquidating once FreeCash > 0
            if user_balance > 0:
                break

            # Close the position using the shared close logic
            # Safety: use max(0, locked - buyback) to prevent negative credit
            # _close_position adds pnl = locked - SV to balance. If SV > locked
            # (shouldn't happen after margin calls, but as safety), pnl would be
            # negative. Override with max(0, ...) for forced liquidation.
            locked = pos['locked_collateral']
            credit = max(0, locked - short_value)

            # Instead of calling _close_position directly (which could produce
            # negative pnl), we replicate its logic with the max(0, ...) safety:
            # 1. Credit FreeCash with max(0, locked - buyback)
            db.execute(
                "UPDATE users SET balance = balance + ? WHERE id = ?",
                (round(credit, 2), user_id)
            )

            # 2. Mark position as closed
            db.execute(
                "UPDATE short_positions SET status = 'closed', closed_at = datetime('now') WHERE id = ?",
                (pos['id'],)
            )

            # 3. Record the transaction (pnl for the transaction record reflects actual P/L)
            pnl = locked - short_value
            _now = datetime.now().isoformat()
            db.execute(
                """INSERT INTO transactions (user_id, ore_id, type, quantity, price_at_trade, total_value, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (user_id, pos['ore_id'], TRANSACTION_TYPE_SHORT_LIQUIDATED,
                 pos['share_quantity'], current_price, round(pnl, 2), _now)
            )

            # 4. Create notification for the player
            _create_liquidation_notification(db, user_id)

            # 5. Add to closed_ids
            closed_ids.add(pos['id'])


def _create_liquidation_notification(db, user_id: int):
    """Create a forced liquidation notification for the player.

    Phase 4 is a catch-all liquidation check — the specific cause (fee or margin)
    may have been handled in Phase 2 or Phase 3. This notification uses a generic
    liquidation message.

    Inserts directly into the notifications table if it exists. Gracefully handles
    the case where the notifications table has not yet been created (the notification
    system is defined in a separate spec).

    Args:
        db: An active sqlite3 connection.
        user_id: The player whose position was liquidated.
    """
    try:
        db.execute(
            """INSERT INTO notifications (user_id, category, message, created_at)
               VALUES (?, ?, ?, datetime('now'))""",
            (
                user_id,
                "liquidation_fee",
                "Forced liquidation: Fee costs depleted your free cash reserves.",
            )
        )
    except Exception:
        # Notifications table may not exist yet (separate spec dependency).
        # Silently skip notification creation.
        pass


def process_short_positions(db):
    """Main entry point called after process_tick(). Handles all active short positions.

    Fetches current ore prices, then runs the four processing phases in strict order:
    1. Evaluate SL/TP triggers (close triggered positions before any fees/margin calls)
    2. Rebalance margin (adjust locked collateral to match current requirements)
    3. Apply time-bleed fees (deduct per-tick fees from FreeCash)
    4. Check forced liquidation (liquidate positions for users at zero FreeCash)

    The entire sequence is wrapped in a top-level try/except so that errors in the
    shorting engine never crash the tick loop. Individual phase functions handle
    per-user error isolation internally.

    Args:
        db: An active sqlite3 connection with row_factory set to sqlite3.Row.
    """
    try:
        # Fetch current ore prices and volatility into a lookup map
        ores_rows = db.execute(
            "SELECT id, current_price, volatility FROM ores"
        ).fetchall()

        ores_map = {
            row['id']: {
                'current_price': float(row['current_price']),
                'volatility': float(row['volatility']),
            }
            for row in ores_rows
        }

        # Phase 1: Evaluate SL/TP triggers
        closed_ids = _evaluate_sltp_triggers(db, ores_map)

        # Phase 2: Rebalance margin (collateral adjustments)
        _rebalance_margin(db, ores_map, closed_ids)

        # Phase 3: Apply time-bleed fees
        _apply_time_bleed_fees(db, ores_map, closed_ids)

        # Phase 4: Check forced liquidation for users at zero FreeCash
        _check_forced_liquidation(db, ores_map, closed_ids)

        # Commit all changes from this tick's short processing
        db.commit()

    except Exception as e:
        logger.error("Error during process_short_positions: %s", e)
        try:
            db.rollback()
        except Exception:
            pass
