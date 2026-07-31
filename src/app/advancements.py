"""
Achievement (Advancement) constants and metadata for OreX.

This module defines the canonical list of advancement keys and their associated
metadata (display name, description, and threshold). Evaluation functions that
use these constants are added in subsequent tasks.

Threshold values correspond to the configuration in app/config.py:
  - ADVANCEMENT_MILLIONAIRE_THRESHOLD = 1_000_000
  - ADVANCEMENT_MULTIMILLIONAIRE_THRESHOLD = 10_000_000
  - ADVANCEMENT_WHAT_A_DEAL_TRADES = 100
  - ADVANCEMENT_SUIT_UP_MINUTES = 20
  - ADVANCEMENT_DEDICATED_STREAK = 3
  - ADVANCEMENT_POST_MORTEM_THRESHOLD = 10_000
"""

import datetime

# Ordered list of all nine advancement keys
ADVANCEMENT_KEYS = [
    "millionaire",
    "multimillionaire",
    "the_big_short",
    "dedicated",
    "day_trader",
    "budding_enthusiast",
    "completionist",
    "tragedy",
    "best_of_the_rest",
]

# Metadata for each advancement: display name, player-facing description, and
# the numeric threshold used by evaluation logic (None where not applicable).
ADVANCEMENT_METADATA = {
    "millionaire": {
        "name": "Millionaire",
        "description": "Reach $1,000,000 net worth",
        "threshold": 1_000_000,
    },
    "multimillionaire": {
        "name": "Multimillionaire",
        "description": "Reach $10,000,000 net worth",
        "threshold": 10_000_000,
    },
    "the_big_short": {
        "name": "The Big Short",
        "description": "Close a profitable short position",
        "threshold": None,
    },
    "dedicated": {
        "name": "Dedicated",
        "description": "Log in 3 days in a row",
        "threshold": 3,
    },
    "day_trader": {
        "name": "What a Deal!",
        "description": "Complete 100 trades",
        "threshold": 100,
    },
    "budding_enthusiast": {
        "name": "Suit Up",
        "description": "Play for 20 minutes",
        "threshold": 20,
    },
    "completionist": {
        "name": "Completionist",
        "description": "Earn all other 8 achievements",
        "threshold": 8,
    },
    "tragedy": {
        "name": "Post-mortem",
        "description": "Reset account when net worth is below $10,000",
        "threshold": 10_000,
    },
    "best_of_the_rest": {
        "name": "Go for Diamond!",
        "description": "Reach rank 1 on the leaderboard",
        "threshold": 1,
    },
}


# --- Core Award & Query Functions ---


def create_notification(db, user_id, category, message, action_url):
    """Insert a notification row directly into the notifications table.

    Wraps in try/except to gracefully handle the case where the
    notifications table does not yet exist (separate spec dependency).
    """
    try:
        db.execute(
            """INSERT INTO notifications (user_id, category, message, action_url, created_at)
               VALUES (?, ?, ?, ?, datetime('now', 'localtime'))""",
            (user_id, category, message, action_url),
        )
    except Exception:
        # Notifications table may not exist yet — silently skip.
        pass


def evaluate_completionist(db, user_id):
    """Evaluate whether the user qualifies for the completionist advancement.

    Called after any other achievement is awarded. Awards completionist
    if the user has earned all 8 other advancements.
    """
    if has_advancement(db, user_id, "completionist"):
        return
    # Count earned advancements excluding completionist
    row = db.execute(
        "SELECT COUNT(*) as cnt FROM advancements WHERE user_id = ? AND advancement_key != 'completionist'",
        (user_id,),
    ).fetchone()
    if row and row["cnt"] == 8:
        award_advancement(db, user_id, "completionist")


def award_advancement(db, user_id, key):
    """Award an advancement to a user. Returns True if newly awarded, False if already owned.

    Uses INSERT OR IGNORE for idempotency. On new award:
    - Handles theme unlock (multimillionaire → money_theme_unlocked=1,
      completionist → gold_theme_unlocked=1)
    - Emits notification via create_notification()
    - Evaluates completionist condition (unless awarding completionist itself)

    Raises ValueError if key is not a valid advancement key.
    """
    if key not in ADVANCEMENT_KEYS:
        raise ValueError(f"Invalid advancement key: {key!r}")

    cursor = db.execute(
        "INSERT OR IGNORE INTO advancements (user_id, advancement_key, earned_at) VALUES (?, ?, datetime('now', 'localtime'))",
        (user_id, key),
    )

    if cursor.rowcount == 0:
        # Already owned
        return False

    # --- Newly awarded ---

    # Theme unlocks
    if key == "multimillionaire":
        db.execute(
            "UPDATE users SET money_theme_unlocked = 1 WHERE id = ?",
            (user_id,),
        )
    elif key == "completionist":
        db.execute(
            "UPDATE users SET gold_theme_unlocked = 1 WHERE id = ?",
            (user_id,),
        )

    # Notification
    display_name = ADVANCEMENT_METADATA[key]["name"]
    message = f"Achievement unlocked: {display_name}!"
    if key == "multimillionaire":
        message += " Money theme unlocked!"
    elif key == "completionist":
        message += " Gold theme unlocked!"

    create_notification(db, user_id, "advancement", message, "/advancements")

    # Evaluate completionist (avoid infinite recursion)
    if key != "completionist":
        evaluate_completionist(db, user_id)

    return True


def has_advancement(db, user_id, key):
    """Check if a player already has a specific advancement.

    Returns True if the advancement exists for the user, False otherwise.
    """
    row = db.execute(
        "SELECT 1 FROM advancements WHERE user_id = ? AND advancement_key = ?",
        (user_id, key),
    ).fetchone()
    return row is not None


def get_user_advancements(db, user_id):
    """Return all earned advancements for a user with earned_at timestamps.

    Returns a list of dicts ordered by earned_at ascending:
        [{"key": "millionaire", "earned_at": "2024-01-15 10:30:00"}, ...]

    If no advancements earned, returns an empty list.
    """
    rows = db.execute(
        "SELECT advancement_key, earned_at FROM advancements WHERE user_id = ? ORDER BY earned_at ASC",
        (user_id,),
    ).fetchall()
    return [{"key": row["advancement_key"], "earned_at": row["earned_at"]} for row in rows]


def get_advancement_progress(db, user_id):
    """Return progress indicators for quantitative advancements.

    Returns a dict with:
        - trade_count: total transactions (all types, including archived)
        - play_time: cumulative minutes of authenticated session time
        - login_streak: current consecutive login day count
        - net_worth: current net worth (balance + holdings + short equity)

    If user not found, returns sensible defaults (all zeros).
    """
    # Get play_time and login_streak from users table
    user_row = db.execute(
        "SELECT play_time, login_streak FROM users WHERE id = ?",
        (user_id,),
    ).fetchone()

    if user_row is None:
        return {"trade_count": 0, "play_time": 0, "login_streak": 0, "net_worth": 0.0}

    play_time = user_row["play_time"]
    login_streak = user_row["login_streak"]

    # Count all transactions (including archived)
    trade_row = db.execute(
        "SELECT COUNT(*) as cnt FROM transactions WHERE user_id = ?",
        (user_id,),
    ).fetchone()
    trade_count = trade_row["cnt"] if trade_row else 0

    # Calculate net worth: balance + holdings value + short position equity
    nw_row = db.execute(
        """SELECT
               u.balance +
               COALESCE((SELECT SUM(h.quantity * o2.current_price)
                         FROM holdings h JOIN ores o2 ON h.ore_id = o2.id
                         WHERE h.user_id = u.id), 0) +
               COALESCE((SELECT SUM(sp.locked_collateral - (sp.share_quantity * o3.current_price))
                         FROM short_positions sp JOIN ores o3 ON sp.ore_id = o3.id
                         WHERE sp.user_id = u.id AND sp.status = 'active'), 0)
               AS net_worth
           FROM users u
           WHERE u.id = ?""",
        (user_id,),
    ).fetchone()
    net_worth = float(nw_row["net_worth"]) if nw_row and nw_row["net_worth"] is not None else 0.0

    return {
        "trade_count": trade_count,
        "play_time": play_time,
        "login_streak": login_streak,
        "net_worth": net_worth,
    }


# --- Login Streak Update ---


def update_login_streak(db, user_id):
    """Called on successful login. Compares today's date with last_streak_date:
    - Same day (or future/clock-skew): no change
    - Yesterday: increment login_streak by 1, update last_streak_date
    - Older/NULL: reset login_streak to 1, set last_streak_date to today
    After update, calls evaluate_login_advancements().
    """
    today = datetime.date.today()

    row = db.execute(
        "SELECT login_streak, last_streak_date FROM users WHERE id = ?",
        (user_id,),
    ).fetchone()

    if row is None:
        return

    current_streak = row["login_streak"] if row["login_streak"] is not None else 0
    last_date_str = row["last_streak_date"]

    if last_date_str is not None:
        last_date = datetime.date.fromisoformat(last_date_str)
        delta = (today - last_date).days

        if delta <= 0:
            # Same day or future (clock skew) — no change
            evaluate_login_advancements(db, user_id)
            return
        elif delta == 1:
            # Yesterday — increment streak
            new_streak = current_streak + 1
        else:
            # More than 1 day gap — reset streak
            new_streak = 1
    else:
        # NULL last_streak_date — first login ever
        new_streak = 1

    db.execute(
        "UPDATE users SET login_streak = ?, last_streak_date = ? WHERE id = ?",
        (new_streak, today.isoformat(), user_id),
    )

    evaluate_login_advancements(db, user_id)


# --- Evaluation Functions (called from trigger points) ---


def evaluate_tick_advancements(db):
    """Evaluate net-worth-based advancements for all eligible players.

    Called after process_tick(db) in the tick engine. Evaluates millionaire,
    multimillionaire, and best_of_the_rest for all players who don't already
    have all three.

    This function is defensive — it will not raise exceptions to avoid
    blocking the tick engine.
    """
    try:
        # Step 1: Get candidate players — those missing at least one of the three
        # net-worth advancements. Calculate net worth in batch.
        candidates = db.execute(
            """SELECT u.id,
                      u.balance +
                      COALESCE((SELECT SUM(h.quantity * o2.current_price)
                                FROM holdings h JOIN ores o2 ON h.ore_id = o2.id
                                WHERE h.user_id = u.id), 0) +
                      COALESCE((SELECT SUM(sp.locked_collateral - (sp.share_quantity * o3.current_price))
                                FROM short_positions sp JOIN ores o3 ON sp.ore_id = o3.id
                                WHERE sp.user_id = u.id AND sp.status = 'active'), 0)
                      AS net_worth
               FROM users u
               WHERE u.id NOT IN (
                   SELECT a.user_id FROM advancements a
                   WHERE a.advancement_key IN ('millionaire', 'multimillionaire', 'best_of_the_rest')
                   GROUP BY a.user_id
                   HAVING COUNT(DISTINCT a.advancement_key) = 3
               )"""
        ).fetchall()

        # Step 2: For each candidate, evaluate millionaire and multimillionaire thresholds
        for row in candidates:
            user_id = row["id"]
            net_worth = float(row["net_worth"]) if row["net_worth"] is not None else 0.0

            try:
                if net_worth >= 1_000_000 and not has_advancement(db, user_id, "millionaire"):
                    award_advancement(db, user_id, "millionaire")

                if net_worth >= 10_000_000 and not has_advancement(db, user_id, "multimillionaire"):
                    award_advancement(db, user_id, "multimillionaire")
            except Exception:
                # Skip this player on error, continue with others
                continue

        # Step 3: Determine rank 1 (best_of_the_rest) — find max net worth across
        # ALL players, then award to all players tied at that maximum.
        rank1_players = db.execute(
            """WITH player_net_worths AS (
                   SELECT u.id,
                          u.balance +
                          COALESCE((SELECT SUM(h.quantity * o2.current_price)
                                    FROM holdings h JOIN ores o2 ON h.ore_id = o2.id
                                    WHERE h.user_id = u.id), 0) +
                          COALESCE((SELECT SUM(sp.locked_collateral - (sp.share_quantity * o3.current_price))
                                    FROM short_positions sp JOIN ores o3 ON sp.ore_id = o3.id
                                    WHERE sp.user_id = u.id AND sp.status = 'active'), 0)
                          AS net_worth
                   FROM users u
               )
               SELECT id FROM player_net_worths
               WHERE net_worth = (SELECT MAX(net_worth) FROM player_net_worths)"""
        ).fetchall()

        for row in rank1_players:
            try:
                user_id = row["id"]
                if not has_advancement(db, user_id, "best_of_the_rest"):
                    award_advancement(db, user_id, "best_of_the_rest")
            except Exception:
                continue

    except Exception:
        # Defensive: tick engine must not be blocked by advancement evaluation failures
        pass


def evaluate_trade_advancement(db, user_id):
    """Called after a trade commit. Awards day_trader if total transactions >= 100."""
    if has_advancement(db, user_id, "day_trader"):
        return
    row = db.execute(
        "SELECT COUNT(*) as cnt FROM transactions WHERE user_id = ?",
        (user_id,),
    ).fetchone()
    trade_count = row["cnt"] if row else 0
    if trade_count >= 100:
        award_advancement(db, user_id, "day_trader")


def evaluate_login_advancements(db, user_id):
    """Called after login streak update. Awards dedicated if login_streak >= 3."""
    if has_advancement(db, user_id, "dedicated"):
        return
    row = db.execute(
        "SELECT login_streak FROM users WHERE id = ?",
        (user_id,),
    ).fetchone()
    if row and row["login_streak"] >= 3:
        award_advancement(db, user_id, "dedicated")


def evaluate_playtime_advancement(db, user_id):
    """Called after play_time increment. Awards budding_enthusiast if play_time >= 20."""
    if has_advancement(db, user_id, "budding_enthusiast"):
        return
    row = db.execute(
        "SELECT play_time FROM users WHERE id = ?",
        (user_id,),
    ).fetchone()
    if row and row["play_time"] >= 20:
        award_advancement(db, user_id, "budding_enthusiast")


def evaluate_short_advancement(db, user_id):
    """Called after a profitable short close. Awards the_big_short.

    IMPORTANT: This function is ONLY called when:
    - profit > 0 (verified by the caller)
    - close_type is 'voluntary' or 'take_profit' (verified by caller)
    - player has advanced_mode active (verified by caller)

    So this function just needs to award the advancement — preconditions
    are already validated at the call site.
    """
    if has_advancement(db, user_id, "the_big_short"):
        return
    award_advancement(db, user_id, "the_big_short")


def evaluate_post_mortem(db, user_id, net_worth):
    """Called before account reset. Awards tragedy if net_worth < $10,000."""
    if has_advancement(db, user_id, "tragedy"):
        return
    if net_worth < 10_000:
        award_advancement(db, user_id, "tragedy")
