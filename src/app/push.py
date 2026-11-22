"""Opt-in Web Push for inbox notifications.

Design in short:
- A push is sent for a notification only when the player is AWAY: no poll from a
  visible page in the last PUSH_PRESENCE_SECONDS. Presence lives in the
  push_settings table, so every process and the engine thread agree.
- The market engine calls process_push_cycle() once per tick (after its own
  commits). It finds fresh, un-toasted notifications for subscribed players and
  claims each one with INSERT OR IGNORE into notification_pushes (the claim is
  atomic, so two engine threads or processes cannot both send it).
- Claimed notifications are handed to a queue drained by one daemon thread per
  process. No network call happens on a request thread or in the engine tick.
- The push service answering 404/410 deletes that subscription.
- Payloads carry notification text, so they are never logged.
"""

import json
import logging
import queue
import re
import sqlite3
import threading
import time
from urllib.parse import urlsplit

logger = logging.getLogger(__name__)

# Inbox notification category -> user-facing push category.
# Categories not listed here never produce a push.
CATEGORY_GROUPS = {
    'stop_loss': 'stop_loss',
    'take_profit': 'take_profit',
    'liquidation': 'liquidation',
    'bonus': 'bonus',
    'achievement': 'achievement',
    'advancement': 'achievement',
}

GROUPS = ('take_profit', 'stop_loss', 'liquidation', 'bonus', 'achievement')
GROUP_COLUMNS = {
    'take_profit': 'notify_take_profit',
    'stop_loss': 'notify_stop_loss',
    'liquidation': 'notify_liquidation',
    'bonus': 'notify_bonus',
    'achievement': 'notify_achievement',
}
GROUP_LABELS = {
    'take_profit': 'Take profit',
    'stop_loss': 'Stop loss',
    'liquidation': 'Liquidations',
    'bonus': 'Daily bonus',
    'achievement': 'Achievements',
}

_TITLES = {
    'stop_loss': 'Stop loss triggered',
    'take_profit': 'Take profit triggered',
    'liquidation': 'Position liquidated',
    'bonus': 'Daily bonus ready',
    'achievement': 'Achievement unlocked',
    'advancement': 'Achievement unlocked',
}

# Web Push Urgency header per push category. Android may hold 'normal' pushes
# during Doze, so time-critical ones are 'high'.
HIGH_URGENCY_GROUPS = ('take_profit', 'stop_loss', 'liquidation', 'test')


def urgency_for(group):
    return 'high' if group in HIGH_URGENCY_GROUPS else 'normal'


# The push service answering one of these means the saved subscription is dead
# (404/410) or was made with another VAPID key (403): delete it so the page
# registers the device again.
DEAD_SUBSCRIPTION_STATUSES = (403, 404, 410)

MAX_BODY_CHARS = 140
PUSH_TTL_SECONDS = 86400
SEND_TIMEOUT_SECONDS = 5
BONUS_CHECK_INTERVAL = 60


# --- Configuration ---------------------------------------------------------

def is_configured(config):
    """True when all three VAPID settings are present and the subject is a URL."""
    subject = config.get('VAPID_SUBJECT') or ''
    return bool(
        config.get('VAPID_PUBLIC_KEY')
        and config.get('VAPID_PRIVATE_KEY')
        and subject.startswith(('mailto:', 'https://'))
    )


# --- Preferences and presence ------------------------------------------------

def get_preferences(db, user_id):
    """Category switches for a player: {group: bool}. Everything is on by default."""
    row = db.execute(
        """SELECT notify_take_profit, notify_stop_loss, notify_liquidation, notify_bonus, notify_achievement
           FROM push_settings WHERE user_id = ?""",
        (user_id,),
    ).fetchone()
    if row is None:
        return {group: True for group in GROUPS}
    return {group: bool(row[GROUP_COLUMNS[group]]) for group in GROUPS}


def set_preferences(db, user_id, updates):
    """Save the given {group: bool} switches. Unknown groups are ignored."""
    changes = {g: bool(v) for g, v in updates.items() if g in GROUP_COLUMNS}
    if not changes:
        return
    db.execute("INSERT OR IGNORE INTO push_settings (user_id) VALUES (?)", (user_id,))
    for group, value in changes.items():
        # Column names come from the fixed GROUP_COLUMNS map, never from input
        db.execute(
            f"UPDATE push_settings SET {GROUP_COLUMNS[group]} = ? WHERE user_id = ?",
            (1 if value else 0, user_id),
        )
    db.commit()


def has_subscription(db, user_id):
    return db.execute(
        "SELECT 1 FROM push_subscriptions WHERE user_id = ? LIMIT 1", (user_id,)
    ).fetchone() is not None


_CLIENT_ID_RE = re.compile(r'[A-Za-z0-9_-]{1,64}')
# Presence rows older than this are dropped when a row is written
PRESENCE_PRUNE_SECONDS = 3600


def clean_client_id(value):
    """The page instance id from a request, or '' when missing or malformed."""
    return value if isinstance(value, str) and _CLIENT_ID_RE.fullmatch(value) else ''


def record_visible_poll(db, user_id, now=None, write_interval=15, client_id=''):
    """Remember that a page of the player polled while visible just now.

    Presence is kept per page instance (client_id), so one device leaving does
    not hide another that is still visible. Only players with a push subscription
    are tracked, and a page's stored time is rewritten only when it is more than
    write_interval seconds old, so this is one cheap read for most polls.
    Returns True when a write happened.
    """
    now = time.time() if now is None else now
    if not has_subscription(db, user_id):
        return False
    cursor = db.execute(
        """INSERT INTO push_presence (user_id, client_id, seen_at) VALUES (?, ?, ?)
           ON CONFLICT(user_id, client_id) DO UPDATE SET seen_at = excluded.seen_at
           WHERE push_presence.seen_at <= excluded.seen_at - ?""",
        (user_id, client_id, now, write_interval),
    )
    written = cursor.rowcount > 0
    if written:
        db.execute(
            "DELETE FROM push_presence WHERE user_id = ? AND seen_at < ?",
            (user_id, now - PRESENCE_PRUNE_SECONDS),
        )
    db.commit()
    return written


def record_left(db, user_id, client_id=''):
    """A page of the player was hidden or closed: forget its presence at once.

    Other pages of the same player keep the account present. Returns True when
    a presence row was removed.
    """
    cursor = db.execute(
        "DELETE FROM push_presence WHERE user_id = ? AND client_id = ?",
        (user_id, client_id),
    )
    db.commit()
    return cursor.rowcount > 0


def is_present(db, user_id, now=None, window=60):
    """True if any of the player's pages polled while visible within `window` seconds."""
    now = time.time() if now is None else now
    row = db.execute(
        "SELECT 1 FROM push_presence WHERE user_id = ? AND seen_at > ? LIMIT 1",
        (user_id, now - window),
    ).fetchone()
    return row is not None


# --- Subscriptions -----------------------------------------------------------

def upsert_subscription(db, user_id, endpoint, p256dh, auth, user_agent=None):
    """Store a device subscription for the player. An endpoint that belonged to
    another account moves to this one."""
    db.execute(
        """INSERT INTO push_subscriptions (user_id, endpoint, p256dh, auth, user_agent)
           VALUES (?, ?, ?, ?, ?)
           ON CONFLICT(endpoint) DO UPDATE SET
               user_id = excluded.user_id, p256dh = excluded.p256dh,
               auth = excluded.auth, user_agent = excluded.user_agent""",
        (user_id, endpoint, p256dh, auth, (user_agent or '')[:200] or None),
    )
    db.commit()


def delete_subscription(db, user_id, endpoint):
    """Remove one of the player's own subscriptions. Returns True if it existed."""
    cursor = db.execute(
        "DELETE FROM push_subscriptions WHERE user_id = ? AND endpoint = ?",
        (user_id, endpoint),
    )
    db.commit()
    return cursor.rowcount > 0


# --- Payload -------------------------------------------------------------------

def _shorten(text, limit=MAX_BODY_CHARS):
    text = ' '.join((text or '').split())
    return text if len(text) <= limit else text[:limit - 1].rstrip() + '\u2026'


def build_payload(notification_id, category, message, action_url):
    """JSON string the service worker shows. Same text as the inbox and toast."""
    return json.dumps({
        'title': _TITLES.get(category, 'OreX'),
        'body': _shorten(message),
        'url': action_url or f'/inbox?selected={notification_id}',
        'tag': f'orex-notification-{notification_id}',
        'category': CATEGORY_GROUPS.get(category),
    })


# --- Sending queue -----------------------------------------------------------------

_queue = queue.Queue(maxsize=1000)
_worker_lock = threading.Lock()
_worker = None
# Tests turn the worker thread off and call drain() themselves.
_worker_enabled = True


def enqueue(job):
    """Queue one send. Never blocks and never raises; a full queue drops the push."""
    try:
        _queue.put_nowait(job)
    except queue.Full:
        logger.warning('Push queue full, dropping a push')
        return
    if _worker_enabled:
        _ensure_worker()


def _ensure_worker():
    global _worker
    with _worker_lock:
        if _worker is not None and _worker.is_alive():
            return
        _worker = threading.Thread(target=_worker_loop, daemon=True, name='PushSender')
        _worker.start()


def _worker_loop():
    while True:
        job = _queue.get()
        try:
            _send_job(job)
        except Exception as exc:
            logger.warning('Push send failed (%s)', type(exc).__name__)


def drain():
    """Send everything queued, on the calling thread. For tests."""
    sent = 0
    while True:
        try:
            job = _queue.get_nowait()
        except queue.Empty:
            return sent
        _send_job(job)
        sent += 1


def _send_job(job):
    """Send one push. 403/404/410 from the push service deletes the subscription."""
    import pywebpush

    try:
        pywebpush.webpush(
            subscription_info={
                'endpoint': job['endpoint'],
                'keys': {'p256dh': job['p256dh'], 'auth': job['auth']},
            },
            data=job['payload'],
            vapid_private_key=job['vapid_private_key'],
            vapid_claims={'sub': job['vapid_subject']},
            ttl=PUSH_TTL_SECONDS,
            timeout=SEND_TIMEOUT_SECONDS,
            headers={'Urgency': job.get('urgency', 'normal')},
        )
    except pywebpush.WebPushException as exc:
        status = getattr(getattr(exc, 'response', None), 'status_code', None)
        # Host only (for example fcm.googleapis.com): tells phone from desktop
        # failures without logging the device-specific endpoint
        host = urlsplit(job['endpoint']).hostname or 'unknown'
        logger.warning('Push service rejected a push (status %s, host %s)', status, host)
        if status in DEAD_SUBSCRIPTION_STATUSES:
            _forget_subscription(job['db_path'], job['subscription_id'])
        return
    _touch_success(job['db_path'], job['subscription_id'])


def _worker_db(db_path):
    conn = sqlite3.connect(db_path, timeout=10)
    conn.execute('PRAGMA foreign_keys=ON')
    return conn


def _forget_subscription(db_path, subscription_id):
    conn = _worker_db(db_path)
    try:
        conn.execute('DELETE FROM push_subscriptions WHERE id = ?', (subscription_id,))
        conn.commit()
    finally:
        conn.close()


def _touch_success(db_path, subscription_id):
    conn = _worker_db(db_path)
    try:
        conn.execute(
            "UPDATE push_subscriptions SET last_success_at = datetime('now') WHERE id = ?",
            (subscription_id,),
        )
        conn.commit()
    finally:
        conn.close()


def count_subscriptions(db, user_id):
    return db.execute(
        "SELECT COUNT(*) FROM push_subscriptions WHERE user_id = ?", (user_id,)
    ).fetchone()[0]


def has_endpoint(db, user_id, endpoint):
    return db.execute(
        "SELECT 1 FROM push_subscriptions WHERE user_id = ? AND endpoint = ?",
        (user_id, endpoint),
    ).fetchone() is not None


def queue_for_user(db, config, db_path, user_id, payload, urgency='normal', endpoint=None):
    """Queue one push per subscription the player has (only the one with the
    given endpoint when set). Returns how many."""
    query = "SELECT id, endpoint, p256dh, auth FROM push_subscriptions WHERE user_id = ?"
    params = [user_id]
    if endpoint:
        query += " AND endpoint = ?"
        params.append(endpoint)
    subs = db.execute(query, params).fetchall()
    for sub in subs:
        enqueue({
            'db_path': db_path,
            'subscription_id': sub['id'],
            'endpoint': sub['endpoint'],
            'p256dh': sub['p256dh'],
            'auth': sub['auth'],
            'payload': payload,
            'vapid_private_key': config['VAPID_PRIVATE_KEY'],
            'vapid_subject': config['VAPID_SUBJECT'],
            'urgency': urgency,
        })
    return len(subs)


# --- Deciding what to push -------------------------------------------------------------

def claim_notification(db, notification_id):
    """Atomically claim a notification for push. True for exactly one caller.

    Also marks it as toasted, so the in-app toast never repeats it.
    """
    cursor = db.execute(
        "INSERT OR IGNORE INTO notification_pushes (notification_id) VALUES (?)",
        (notification_id,),
    )
    claimed = cursor.rowcount == 1
    if claimed:
        db.execute("UPDATE notifications SET toasted = 1 WHERE id = ?", (notification_id,))
    db.commit()
    return claimed


def sweep_pending_pushes(db, config, db_path, now=None):
    """Push fresh notifications for players who are away. Returns how many were claimed.

    A notification qualifies when it is recent, has not been shown as a toast or
    claimed yet, maps to a push category the player has on, the player has a
    subscription, and the player is not present.
    """
    if not is_configured(config):
        return 0
    now = time.time() if now is None else now
    max_age = int(config.get('PUSH_MAX_AGE_SECONDS', 300))
    window = config.get('PUSH_PRESENCE_SECONDS', 60)

    rows = db.execute(
        """SELECT n.id, n.user_id, n.category, n.message, n.action_url
           FROM notifications n
           WHERE n.toasted = 0
             AND n.created_at >= datetime('now', 'localtime', ?)
             AND NOT EXISTS (SELECT 1 FROM notification_pushes p WHERE p.notification_id = n.id)
             AND EXISTS (SELECT 1 FROM push_subscriptions s WHERE s.user_id = n.user_id)
             AND NOT EXISTS (SELECT 1 FROM users u WHERE u.id = n.user_id AND u.suspended_at IS NOT NULL)
           ORDER BY n.id ASC LIMIT 200""",
        (f'-{max_age} seconds',),
    ).fetchall()

    claimed = 0
    for row in rows:
        group = CATEGORY_GROUPS.get(row['category'])
        if group is None:
            continue
        if not get_preferences(db, row['user_id'])[group]:
            continue
        if is_present(db, row['user_id'], now, window):
            continue
        if not claim_notification(db, row['id']):
            continue
        claimed += 1
        payload = build_payload(row['id'], row['category'], row['message'], row['action_url'])
        queue_for_user(db, config, db_path, row['user_id'], payload, urgency_for(group))
    return claimed


_last_bonus_check = 0.0


def schedule_bonus_reminders(app, db):
    """Create today's daily-bonus reminder for subscribed players at the moment
    the bonus becomes available, so an away player can be pushed.

    Uses the existing ensure_bonus_reminder (same notification, same once-a-day
    rule). Only players with a subscription and the bonus switch on are checked.
    """
    from app.bonus import ensure_bonus_reminder

    rows = db.execute(
        """SELECT DISTINCT s.user_id FROM push_subscriptions s
           LEFT JOIN push_settings p ON p.user_id = s.user_id
           JOIN users u ON u.id = s.user_id
           WHERE COALESCE(p.notify_bonus, 1) = 1 AND u.suspended_at IS NULL"""
    ).fetchall()
    if not rows:
        return
    from app.database import get_db
    with app.app_context():
        flask_db = get_db()
        for row in rows:
            try:
                ensure_bonus_reminder(flask_db, row['user_id'])
            except Exception:
                logger.warning('Daily bonus reminder check failed for a player')


def process_push_cycle(app, db):
    """One engine pass: bonus reminders (at most once a minute), then the sweep.

    Cheap when push is not configured or nobody subscribed. Never raises.
    """
    global _last_bonus_check
    try:
        if not is_configured(app.config):
            return
        now = time.time()
        if now - _last_bonus_check >= BONUS_CHECK_INTERVAL:
            _last_bonus_check = now
            schedule_bonus_reminders(app, db)
        sweep_pending_pushes(db, app.config, app.config['DATABASE_PATH'], now)
    except Exception as exc:
        logger.warning('Push cycle failed (%s)', type(exc).__name__)
