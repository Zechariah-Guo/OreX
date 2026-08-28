"""Inbox blueprint — notification polling and inbox page endpoints."""

from flask import Blueprint, abort, jsonify, render_template, request
from flask_login import current_user, login_required

from app.models import (
    delete_notification,
    get_new_notifications_since,
    get_notification_detail,
    get_notification_style,
    get_notifications,
    get_pending_toasts,
    has_unread_notifications,
    mark_all_notifications_read,
    mark_notification_read,
    mark_notifications_toasted,
)

inbox_bp = Blueprint("inbox", __name__, url_prefix="/inbox")


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


@inbox_bp.route("")
@login_required
def inbox_page():
    """Full inbox page with notification list and empty detail panel.

    Query params:
        filter: One of 'all', 'read', 'unread' (default 'all').
        selected: Optional notification ID to pre-load in the detail panel.
    """
    current_filter = request.args.get("filter", "all")
    if current_filter not in _VALID_FILTERS:
        current_filter = "all"

    rows = get_notifications(current_user.id, filter=current_filter)
    notifications = _enrich_notifications(rows)

    # Pre-load a selected notification's detail if specified
    selected_notification = None
    selected_css_class = None
    selected_icon = None
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
        except (TypeError, ValueError):
            pass

    return render_template(
        "pages/inbox.html",
        notifications=notifications,
        current_filter=current_filter,
        selected_notification=selected_notification,
        selected_css_class=selected_css_class,
        selected_icon=selected_icon,
    )


@inbox_bp.route("/<int:id>")
@login_required
def inbox_detail(id):
    """Detail panel partial for a single notification (htmx).

    Returns 404 if the notification doesn't exist or doesn't belong to user.
    """
    row = get_notification_detail(id, current_user.id)
    if row is None:
        abort(404)

    css_class, icon, _duration = get_notification_style(row["category"])

    return render_template(
        "partials/inbox_detail.html",
        notification=row,
        css_class=css_class,
        icon=icon,
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
    )


@inbox_bp.route("/mark-all-read", methods=["POST"])
@login_required
def inbox_mark_all_read():
    """Mark all notifications as read and return the updated list partial."""
    mark_all_notifications_read(current_user.id)

    rows = get_notifications(current_user.id, filter="all")
    notifications = _enrich_notifications(rows)

    return render_template(
        "partials/inbox_list.html",
        notifications=notifications,
        current_filter="all",
    )


@inbox_bp.route("/<int:id>", methods=["DELETE"])
@login_required
def inbox_delete(id):
    """Delete a notification and return the updated list partial.

    Returns 404 if the notification doesn't exist or doesn't belong to user.
    """
    success = delete_notification(id, current_user.id)
    if not success:
        abort(404)

    rows = get_notifications(current_user.id, filter="all")
    notifications = _enrich_notifications(rows)

    return render_template(
        "partials/inbox_list.html",
        notifications=notifications,
        current_filter="all",
    )
