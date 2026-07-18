"""Market engine — background thread running the 30-second tick loop.

The engine uses its own database connection (separate from Flask's
per-request connection) to avoid threading issues with SQLite.
"""

import atexit
import logging
import signal
import sqlite3
import threading
import time
from datetime import datetime

logger = logging.getLogger(__name__)

_engine_thread = None
_shutdown_event = threading.Event()


def stop_engine():
    """Signal the engine thread to stop gracefully."""
    _shutdown_event.set()


def start_engine(app):
    """Start the market engine background thread.

    Only starts if not already running and not in the reloader child process
    (avoids double-starting in debug mode).
    """
    global _engine_thread

    # In debug mode with reloader, Flask spawns two processes.
    # Only start the engine in the reloader child (WERKZEUG_RUN_MAIN=true).
    import os
    if app.debug and os.environ.get('WERKZEUG_RUN_MAIN') != 'true':
        return

    if _engine_thread is not None and _engine_thread.is_alive():
        return

    db_path = app.config['DATABASE_PATH']
    tick_interval = app.config['TICK_INTERVAL']
    default_balance = app.config['DEFAULT_BALANCE']

    def tick_loop():
        """Main tick loop — runs until shutdown is signalled."""
        # Create a dedicated database connection for this thread
        db = sqlite3.connect(db_path)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA foreign_keys=ON")

        # Ensure bot users exist in the database
        from app.market.bots import ensure_bots_exist
        ensure_bots_exist(db, default_balance)

        from app.market.algorithm import process_tick
        from app.market.shorting import process_short_positions

        try:
            while not _shutdown_event.is_set():
                # Use event.wait instead of time.sleep so we can wake up quickly on shutdown
                if _shutdown_event.wait(timeout=tick_interval):
                    break
                try:
                    process_tick(db)
                except Exception as e:
                    # Log error but keep the engine running
                    print(f"[Market Engine] Error during tick: {e}")
                    try:
                        db.rollback()
                    except Exception:
                        pass

                try:
                    process_short_positions(db)
                except Exception as e:
                    # Log error but keep the engine running — shorting errors
                    # must not block the main tick loop
                    print(f"[Market Engine] Error during short position processing: {e}")
                    try:
                        db.rollback()
                    except Exception:
                        pass

                try:
                    evaluate_stop_loss_take_profit(db)
                except Exception as e:
                    # Log error but keep the engine running
                    print(f"[Market Engine] Error during SL/TP evaluation: {e}")
                    try:
                        db.rollback()
                    except Exception:
                        pass
        finally:
            db.close()
            print("[Market Engine] Database connection closed.")

    _engine_thread = threading.Thread(target=tick_loop, daemon=True, name='MarketEngine')
    _engine_thread.start()
    print(f"[Market Engine] Started — ticking every {tick_interval}s")

    # Register shutdown handler so db.close() is called on Ctrl+C / process exit
    atexit.register(stop_engine)

    def _signal_handler(signum, frame):
        stop_engine()
        # Give the thread a moment to close the db connection
        _engine_thread.join(timeout=2)
        raise SystemExit(0)

    # Only override signal handlers in the main thread
    if threading.current_thread() is threading.main_thread():
        signal.signal(signal.SIGINT, _signal_handler)
        signal.signal(signal.SIGTERM, _signal_handler)


def evaluate_stop_loss_take_profit(db):
    """Check all active SL/TP orders against current prices and execute triggered ones.

    For each active order, compares the ore's current price against the stop_loss
    and take_profit thresholds. If triggered, executes an auto-sell: credits the
    user's balance, deletes the holding, marks the order as triggered, and records
    a transaction.

    Each order is evaluated independently — errors on one order do not prevent
    processing of the remaining orders.
    """
    orders = db.execute("""
        SELECT sltp.id AS sltp_id, sltp.stop_loss, sltp.take_profit,
               sltp.holding_id, h.quantity, h.user_id, h.ore_id,
               o.current_price
        FROM stop_loss_take_profit sltp
        JOIN holdings h ON sltp.holding_id = h.id
        JOIN ores o ON h.ore_id = o.id
        WHERE sltp.active = 1
    """).fetchall()

    for order in orders:
        try:
            triggered = False
            if order['stop_loss'] is not None and order['current_price'] <= order['stop_loss']:
                triggered = True
            elif order['take_profit'] is not None and order['current_price'] >= order['take_profit']:
                triggered = True

            if not triggered:
                continue

            # Calculate sell proceeds
            quantity = order['quantity']
            current_price = order['current_price']
            total_value = quantity * current_price

            # Credit the user's balance
            db.execute(
                "UPDATE users SET balance = balance + ? WHERE id = ?",
                (total_value, order['user_id'])
            )

            # Delete the holding (full sell of entire holding)
            db.execute(
                "DELETE FROM holdings WHERE id = ?",
                (order['holding_id'],)
            )

            # Mark the SL/TP order as triggered
            db.execute(
                "UPDATE stop_loss_take_profit SET active = 0, triggered_at = datetime('now') WHERE id = ?",
                (order['sltp_id'],)
            )

            # Record the auto-sell transaction
            now = datetime.now().isoformat()
            db.execute(
                """INSERT INTO transactions (user_id, ore_id, type, quantity, price_at_trade, total_value, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (order['user_id'], order['ore_id'], 'sell', quantity, current_price, total_value, now)
            )

        except Exception as e:
            logger.error(
                "Error evaluating SL/TP order %s for user %s: %s",
                order['sltp_id'], order['user_id'], e
            )
            continue

    db.commit()
