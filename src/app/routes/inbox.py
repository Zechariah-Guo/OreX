"""Inbox blueprint — notification polling and inbox page endpoints."""

from flask import Blueprint, abort, jsonify, render_template, request
from flask_login import current_user, login_required

from app.advancements import advancement_key_from_message, get_advancement_detail
from app.bonus import (
    BONUS_AMOUNTS,
    ensure_bonus_reminder,
    get_bonus_amount,
    is_bonus_available,
    is_bonus_complete,
)
from app.database import get_db
from app.models import (
    delete_notification,
    delete_notifications,
    get_new_notifications_since,
    get_notification_detail,
    get_notification_trade,
    get_notification_style,
    get_notifications,
    get_pending_toasts,
    has_unread_notifications,
    mark_notification_read,
    mark_notifications_read,
    mark_notifications_toasted,
)

inbox_bp = Blueprint("inbox", __name__, url_prefix="/inbox")


def _bonus_for(row):
    """Live 3-day bonus state for a bonus reminder, else None.

    Uses the player's state *now*, not when the reminder was sent: the reminder
    may be from an earlier day, or the bonus may already have been collected.
    """
    if row is None or row["category"] != "bonus":
        return None
    user = get_db().execute(
        "SELECT bonus_cycle_day, last_bonus_collected_date FROM users WHERE id = ?",
        (current_user.id,),
    ).fetchone()
    if user is None:
        return None

    cycle_day = user["bonus_cycle_day"]
    available = is_bonus_available(user)
    days = []
    for day in (1, 2, 3):
        if day < cycle_day:
            state = "collected"
        elif day == cycle_day:
            state = "ready" if available else "waiting"
        else:
            state = "upcoming"
        days.append({"day": day, "amount": BONUS_AMOUNTS[day], "state": state})

    return {
        "days": days,
        "cycle_day": cycle_day,
        "available": available,
        "complete": is_bonus_complete(cycle_day),
        "amount": get_bonus_amount(cycle_day),
    }


_TRADE_CATEGORIES = ("stop_loss", "take_profit", "liquidation")


def _trade_for(row):
    """Trade summary for an SL/TP or liquidation notification, else None.

    Only notifications created after the transaction_id column existed have
    one; older ones return None and keep the generic layout.
    """
    if row is None or row["category"] not in _TRADE_CATEGORIES:
        return None
    if "transaction_id" not in row.keys():
        return None
    txn = get_notification_trade(row["transaction_id"], current_user.id)
    if txn is None:
        return None

    shares = txn["quantity"]
    fill_price = txn["price_at_trade"]
    trade = {
        "ore_id": txn["ore_id"],
        "ore_name": txn["ore_name"],
        "icon_filename": txn["icon_filename"],
        # Long positions close with a 'sell'; shorts with short_close / short_liquidated
        "side": "Long" if txn["type"] == "sell" else "Short",
        "shares": shares,
        "fill_price": fill_price,
        "trigger_price": row["trigger_price"],
    }

    if row["category"] == "liquidation":
        # For short transactions total_value is the P/L (vault - buyback)
        pnl = txn["total_value"]
        buyback = shares * fill_price
        trade.update({
            "buyback_cost": buyback,
            "collateral_locked": pnl + buyback,
            "returned": max(0.0, pnl),
        })
    return trade


def _advancement_for(row):
    """Badge display data for an advancement notification, else None."""
    if row is None or row["category"] not in ("advancement", "achievement"):
        return None
    key = advancement_key_from_message(row["message"])
    return get_advancement_detail(key) if key else None


@inbox_bp.route("/poll")
@login_required
def poll():
    """Poll for pending toast notifications.

    Returns notifications that haven't been toasted yet (toasted=0),
    marks them as toasted, and returns the has_unread flag for the red dot.
    Each notification fires as a toast exactly once.

    Returns:
        JSON with notifications list and has_unread flag.
    """
    # Daily bonus reminder: once per day, if a bonus is waiting. Must never break polling.
    try:
        ensure_bonus_reminder(get_db(), current_user.id)
    except Exception:
        pass

    rows = get_pending_toasts(current_user.id)
    unread = has_unread_notifications(current_user.id)

    notifications = []
    ids_to_mark = []
    for row in rows:
        css_class, icon, duration = get_notification_style(row["category"])
        notifications.append(
            {
                "id": row["id"],
                "category": row["category"],
                "message": row["message"],
                "action_url": row["action_url"],
                "created_at": row["created_at"],
                "css_class": css_class,
                "icon": icon,
                "duration": duration,
            }
        )
        ids_to_mark.append(row["id"])

    # Mark as toasted so they never fire again
    mark_notifications_toasted(ids_to_mark)

    return jsonify(
        {
            "notifications": notifications,
            "has_unread": unread,
        }
    )

_VALID_FILTERS = ("all", "read", "unread")

def _enrich_notifications(rows):
    """Attach style data (css_class, icon) to each notification row.

    Returns a list of dicts with all row fields plus css_class and icon.
    """
    enriched = []
    for row in rows:
        css_class, icon, _duration = get_notification_style(row["category"])
        enriched.append(
            {
                "id": row["id"],
                "user_id": row["user_id"],
                "category": row["category"],
                "message": row["message"],
                "action_url": row["action_url"],
                "is_read": row["is_read"],
                "created_at": row["created_at"],
                "css_class": css_class,
                "icon": icon,
            }
        )
    return enriched


_MAX_BULK_IDS = 500


@inbox_bp.after_request
def _add_unread_header(response):
    """Tell the page whether unread notifications remain, so the navbar dot can
    update straight after a read/delete without waiting for the next poll."""
    if request.method != "GET" and current_user.is_authenticated:
        response.headers["X-Inbox-Has-Unread"] = "1" if has_unread_notifications(current_user.id) else "0"
    return response


def _request_filter():
    """The list filter named in the query string or form, defaulting to 'all'."""
    value = request.values.get("filter", "all")
    return value if value in _VALID_FILTERS else "all"


def _list_partial():
    """Render the notification list (current filter) for a fetch swap."""
    current_filter = _request_filter()
    rows = get_notifications(current_user.id, filter=current_filter)
    return render_template(
        "partials/inbox_list.html",
        notifications=_enrich_notifications(rows),
        current_filter=current_filter,
    )


def _posted_ids():
    """Notification IDs from the 'ids' form field, ignoring anything not an int."""
    ids = []
    for raw in request.form.getlist("ids")[:_MAX_BULK_IDS]:
        try:
            ids.append(int(raw))
        except (TypeError, ValueError):
            continue
    return ids


@inbox_bp.route("")
@login_required
def inbox_page():
    """Full inbox page: the list, select mode and a full-screen detail view.

    Query params:
        filter: One of 'all', 'read', 'unread' (default 'all').
        selected: Optional notification ID to open straight into the detail view.
    """
    current_filter = _request_filter()

    # Open a selected notification's detail if specified (toast and advancement
    # links deep-link here). Done before the list is read so the list shows it as read.
    selected_notification = None
    selected_css_class = None
    selected_icon = None
    selected_advancement = None
    selected_trade = None
    selected_bonus = None
    selected_id = request.args.get("selected")
    if selected_id:
        try:
            selected_id = int(selected_id)
            row = get_notification_detail(selected_id, current_user.id)
            if row:
                # Auto-mark as read when opened via direct link
                mark_notification_read(selected_id, current_user.id)
                row = get_notification_detail(selected_id, current_user.id)
                selected_notification = row
                selected_css_class, selected_icon, _ = get_notification_style(row["category"])
                selected_advancement = _advancement_for(row)
                selected_trade = _trade_for(row)
                selected_bonus = _bonus_for(row)
        except (TypeError, ValueError):
            pass

    rows = get_notifications(current_user.id, filter=current_filter)
    notifications = _enrich_notifications(rows)

    return render_template(
        "pages/inbox.html",
        notifications=notifications,
        current_filter=current_filter,
        selected_notification=selected_notification,
        selected_css_class=selected_css_class,
        selected_icon=selected_icon,
        selected_advancement=selected_advancement,
        selected_trade=selected_trade,
        selected_bonus=selected_bonus,
    )


@inbox_bp.route("/<int:id>/read", methods=["POST"])
@login_required
def inbox_mark_read(id):
    """Mark a notification as read and return its detail partial.

    Returns 404 if the notification doesn't exist or doesn't belong to user.
    """
    row = get_notification_detail(id, current_user.id)
    if row is None:
        abort(404)

    mark_notification_read(id, current_user.id)

    # Re-fetch to get updated is_read status
    row = get_notification_detail(id, current_user.id)
    css_class, icon, _duration = get_notification_style(row["category"])

    return render_template(
        "partials/inbox_detail.html",
        notification=row,
        css_class=css_class,
        icon=icon,
        advancement=_advancement_for(row),
        trade=_trade_for(row),
        bonus=_bonus_for(row),
    )


@inbox_bp.route("/bulk-read", methods=["POST"])
@login_required
def inbox_bulk_read():
    """Mark the posted 'ids' as read and return the list partial for 'filter'."""
    mark_notifications_read(_posted_ids(), current_user.id)
    return _list_partial()


@inbox_bp.route("/bulk-delete", methods=["POST"])
@login_required
def inbox_bulk_delete():
    """Delete the posted 'ids' (no undo) and return the list partial for 'filter'."""
    delete_notifications(_posted_ids(), current_user.id)
    return _list_partial()


@inbox_bp.route("/<int:id>", methods=["DELETE"])
@login_required
def inbox_delete(id):
    """Delete a notification and return the list partial for the 'filter' query param.

    Returns 404 if the notification doesn't exist or doesn't belong to user.
    """
    success = delete_notification(id, current_user.id)
    if not success:
        abort(404)
    return _list_partial()
