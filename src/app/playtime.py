"""
Play Time Tracker for OreX.

Session-based play time accumulation with periodic DB flushes.
On each authenticated request, checks session['last_heartbeat'] timestamp.
If >= 60 seconds have elapsed, increments play_time in DB (capped at 5 minutes
per heartbeat to prevent stale/zombie sessions from awarding unbounded time).

Multiple tabs: Flask sessions are shared across tabs in the same browser,
so the single session timestamp prevents double-counting.
"""

import math
import time

from flask import current_app, session

from app.advancements import evaluate_playtime_advancement
from app.database import get_db


def get_session_start_key(user_id):
    """Return the Flask session key for tracking this user's last heartbeat."""
    return f"last_heartbeat_{user_id}"


def record_heartbeat(user_id):
    """Called on each authenticated request (throttled to once per minute via session timestamp).

    Increments play_time by elapsed minutes since last heartbeat (capped at 5 min to handle
    stale sessions). Triggers achievement evaluation when play_time crosses 20 min.
    """
    now = time.time()
    session_key = get_session_start_key(user_id)
    last_heartbeat = session.get(session_key)

    if last_heartbeat is None:
        # First request in this session — initialize the timestamp, no time awarded
        session[session_key] = now
        return

    interval = current_app.config.get("PLAYTIME_HEARTBEAT_INTERVAL", 60)
    max_increment = current_app.config.get("PLAYTIME_MAX_INCREMENT", 5)

    elapsed = now - last_heartbeat

    if elapsed < interval:
        # Not enough time has passed since the last heartbeat
        return

    # Compute minutes to award: floor(elapsed / 60), capped at max_increment
    elapsed_minutes = min(math.floor(elapsed / 60), max_increment)

    if elapsed_minutes <= 0:
        return

    db = get_db()

    # Get current play_time before increment (for threshold detection)
    row = db.execute(
        "SELECT play_time FROM users WHERE id = ?", (user_id,)
    ).fetchone()
    previous_play_time = row["play_time"] if row else 0

    # Flush minutes to DB
    flush_playtime(db, user_id, elapsed_minutes)

    # Update session timestamp to now
    session[session_key] = now

    # Evaluate playtime advancement when play_time crosses 20 min threshold
    new_play_time = previous_play_time + elapsed_minutes
    if previous_play_time < 20 <= new_play_time or new_play_time >= 20:
        evaluate_playtime_advancement(db, user_id)

    db.commit()


def flush_playtime(db, user_id, minutes):
    """Atomically increment the user's play_time column by the given minutes."""
    db.execute(
        "UPDATE users SET play_time = play_time + ? WHERE id = ?",
        (minutes, user_id),
    )


def reset_playtime(db, user_id):
    """Set play_time to 0 for the given user (used during account reset)."""
    db.execute(
        "UPDATE users SET play_time = 0 WHERE id = ?",
        (user_id,),
    )
