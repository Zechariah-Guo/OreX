"""Market engine — background thread running the 30-second tick loop.

The engine uses its own database connection (separate from Flask's
per-request connection) to avoid threading issues with SQLite.
"""

import atexit
import signal
import sqlite3
import threading
import time

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
