"""Web Push endpoints: device subscriptions, category switches and a test push.

Every POST is CSRF-protected (the page sends the token in X-CSRFToken, or in the
csrf_token form field for the away beacon) and acts only on the logged-in
player's own rows.
"""

import json
import time

from flask import Blueprint, current_app, jsonify, request
from flask_login import current_user, login_required
from flask_wtf.csrf import generate_csrf

from app import push
from app.database import get_db

push_bp = Blueprint('push', __name__, url_prefix='/push')

MAX_SUBSCRIPTIONS_PER_USER = 10
_MAX_FIELD = 1000


def _no_store(response):
    response.headers['Cache-Control'] = 'no-store'
    return response


def _not_configured():
    return jsonify({'error': 'not_configured'}), 503


def _text(value, limit=_MAX_FIELD):
    """A non-empty string no longer than limit, else None."""
    if isinstance(value, str) and 0 < len(value) <= limit:
        return value
    return None


@push_bp.route('/config')
def config():
    """Public key for the browser, plus a CSRF token for the signed-in session
    (the service worker uses it to re-register after a subscription change)."""
    configured = push.is_configured(current_app.config)
    body = {
        'configured': configured,
        'key': current_app.config['VAPID_PUBLIC_KEY'] if configured else '',
    }
    if current_user.is_authenticated:
        body['csrf'] = generate_csrf()
    return _no_store(jsonify(body))


@push_bp.route('/subscribe', methods=['POST'])
@login_required
def subscribe():
    """Save this device's subscription for the current player (upsert by endpoint)."""
    if not push.is_configured(current_app.config):
        return _not_configured()
    data = request.get_json(silent=True) or {}
    keys = data.get('keys') if isinstance(data.get('keys'), dict) else {}
    endpoint = _text(data.get('endpoint'))
    p256dh = _text(keys.get('p256dh'), 200)
    auth = _text(keys.get('auth'), 100)
    if not endpoint or not endpoint.startswith('https://') or not p256dh or not auth:
        return jsonify({'error': 'invalid_subscription'}), 400

    db = get_db()
    push.upsert_subscription(
        db, current_user.id, endpoint, p256dh, auth,
        request.headers.get('User-Agent'),
    )
    # Keep the newest few devices per account
    db.execute(
        """DELETE FROM push_subscriptions WHERE user_id = ? AND id NOT IN (
               SELECT id FROM push_subscriptions WHERE user_id = ? ORDER BY id DESC LIMIT ?)""",
        (current_user.id, current_user.id, MAX_SUBSCRIPTIONS_PER_USER),
    )
    db.commit()
    return jsonify({'subscribed': True, 'devices': push.count_subscriptions(db, current_user.id)})


@push_bp.route('/status')
@login_required
def status():
    """Whether the server has this device saved for the current player, and how
    many devices the player has notifications on for. ?endpoint= is optional."""
    db = get_db()
    endpoint = _text(request.args.get('endpoint'))
    return _no_store(jsonify({
        'subscribed': bool(endpoint) and push.has_endpoint(db, current_user.id, endpoint),
        'devices': push.count_subscriptions(db, current_user.id),
    }))


@push_bp.route('/unsubscribe', methods=['POST'])
@login_required
def unsubscribe():
    """Remove this device's subscription (only if it belongs to the current player)."""
    data = request.get_json(silent=True) or {}
    endpoint = _text(data.get('endpoint'))
    if not endpoint:
        return jsonify({'error': 'invalid_subscription'}), 400
    removed = push.delete_subscription(get_db(), current_user.id, endpoint)
    return jsonify({'subscribed': False, 'removed': removed})


@push_bp.route('/preferences', methods=['POST'])
@login_required
def preferences():
    """Save category switches. Body: JSON like {"take_profit": false}; omitted ones are kept.
    Unknown keys and non-boolean values are rejected."""
    data = request.get_json(silent=True)
    if not isinstance(data, dict) or not data:
        return jsonify({'error': 'invalid_preferences'}), 400
    if any(g not in push.GROUPS or not isinstance(v, bool) for g, v in data.items()):
        return jsonify({'error': 'invalid_preferences'}), 400
    db = get_db()
    push.set_preferences(db, current_user.id, data)
    return jsonify({'preferences': push.get_preferences(db, current_user.id)})


@push_bp.route('/away', methods=['POST'])
def away():
    """A page of the current player was hidden or closed: stop counting it as present.

    Sent by navigator.sendBeacon, which cannot set headers, so the CSRF token
    arrives as the form field csrf_token (checked by CSRFProtect like any POST).
    Signed-out callers get a plain 401: login_required would flash a message
    into a session that is on its way out (for example right after logout).
    """
    if not current_user.is_authenticated:
        return '', 401
    push.record_left(get_db(), current_user.id, push.clean_client_id(request.form.get('client_id')))
    return '', 204


@push_bp.route('/test', methods=['POST'])
@login_required
def test():
    """Send a test push (once per cooldown). With an "endpoint" in the JSON body
    only that device of the current player gets it, otherwise all of them."""
    cfg = current_app.config
    if not push.is_configured(cfg):
        return _not_configured()
    db = get_db()
    data = request.get_json(silent=True)
    endpoint = _text(data.get('endpoint')) if isinstance(data, dict) else None
    if endpoint:
        known = push.has_endpoint(db, current_user.id, endpoint)
    else:
        known = push.has_subscription(db, current_user.id)
    if not known:
        return jsonify({'error': 'no_subscription'}), 400

    now = time.time()
    cooldown = cfg['PUSH_TEST_COOLDOWN']
    db.execute('INSERT OR IGNORE INTO push_settings (user_id) VALUES (?)', (current_user.id,))
    cursor = db.execute(
        'UPDATE push_settings SET last_test_at = ? WHERE user_id = ? AND last_test_at <= ?',
        (now, current_user.id, now - cooldown),
    )
    db.commit()
    if cursor.rowcount == 0:
        return jsonify({'error': 'too_soon', 'retry_after': cooldown}), 429

    payload = json.dumps({
        'title': 'OreX test notification',
        'body': 'Notifications are working on this device.',
        'url': '/settings',
        'tag': 'orex-test',
        'category': 'test',
    })
    sent = push.queue_for_user(
        db, cfg, cfg['DATABASE_PATH'], current_user.id, payload,
        push.urgency_for('test'), endpoint,
    )
    return jsonify({'queued': sent})
