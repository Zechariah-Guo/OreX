"""Tutorial blueprint — guided onboarding overlay endpoints."""

from flask import Blueprint, abort, jsonify, request
from flask_login import current_user, login_required

from app.advanced import get_advanced_status
from app.tutorial.data import ADVANCED_ONLY_TRACKS, get_track_length, load_track
from app.tutorial.models import (
    advance_step,
    complete_tutorial,
    create_or_update_tutorial_state,
    dismiss_tutorial,
    get_all_tutorial_states,
    get_tutorial_state,
    pick_active_state,
    replay_tutorial,
    should_auto_trigger,
)

tutorial_bp = Blueprint("tutorial", __name__, url_prefix="/tutorial")


def _json_body():
    """Return the request's JSON body as a dict (empty dict if absent/invalid)."""
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


def _get_track_or_abort(track_id):
    """Return the track dict for track_id.

    Aborts 404 if the track is unknown, and 403 if it is an Advanced-only
    track the current user has not unlocked.
    """
    if not isinstance(track_id, str):
        abort(404)
    track = load_track(track_id)
    if track is None:
        abort(404)
    if track_id in ADVANCED_ONLY_TRACKS:
        if not get_advanced_status(current_user.id)["purchased"]:
            abort(403)
    return track


def _step_route(track, index):
    """Return the route of the step at index, or None if out of range."""
    steps = track["steps"]
    if 0 <= index < len(steps):
        return steps[index].get("route")
    return None


@tutorial_bp.route("/track/<track_id>")
@login_required
def get_track(track_id):
    """Return the full step definitions for a track as JSON."""
    return jsonify(_get_track_or_abort(track_id))


@tutorial_bp.route("/state")
@login_required
def get_state():
    """Return the in-progress tutorial state for client init, or null."""
    active = pick_active_state(get_all_tutorial_states(current_user.id))
    if active is None:
        return jsonify(None)
    return jsonify({
        "track_id": active["track_id"],
        "step_index": active["current_step_index"],
        "status": active["status"],
    })


@tutorial_bp.route("/start", methods=["POST"])
@login_required
def start():
    """Begin a track for the first time (auto-trigger).

    Creates the progress record as in_progress at step 0. Only succeeds when
    the track is eligible to auto-trigger; otherwise returns 409 so a stale
    client cannot restart a completed or dismissed tutorial (use /replay).
    """
    track_id = _json_body().get("track_id")
    track = _get_track_or_abort(track_id)

    state = get_tutorial_state(current_user.id, track_id)
    if state is not None and state["status"] == "in_progress":
        # Already running (e.g. double request): report current position
        return jsonify({"ok": True, "step_index": state["current_step_index"]})

    if not should_auto_trigger(current_user.id, track_id):
        return jsonify({"ok": False, "error": "tutorial already finished"}), 409

    create_or_update_tutorial_state(current_user.id, track_id, "in_progress", 0)
    return jsonify({"ok": True, "step_index": 0, "route": _step_route(track, 0)})


@tutorial_bp.route("/advance", methods=["POST"])
@login_required
def advance():
    """Move an in-progress track to a new step index.

    Returns next_page: the new step's route when it differs from the
    previous step's route (cross-page navigation needed), otherwise null.
    """
    data = _json_body()
    track_id = data.get("track_id")
    step_index = data.get("step_index")
    track = _get_track_or_abort(track_id)

    state = get_tutorial_state(current_user.id, track_id)
    if state is None:
        abort(404)
    if state["status"] != "in_progress":
        return jsonify({"ok": False, "error": "tutorial is not in progress"}), 409

    if (not isinstance(step_index, int) or isinstance(step_index, bool)
            or step_index < 0 or step_index >= get_track_length(track_id)):
        return jsonify({"ok": False, "error": "invalid step_index"}), 400

    advance_step(current_user.id, track_id, step_index)

    old_route = _step_route(track, state["current_step_index"])
    new_route = _step_route(track, step_index)
    next_page = new_route if new_route != old_route else None
    return jsonify({"ok": True, "next_page": next_page})


def _end_advanced_cleanup(track_id):
    """Clear the demo short when the Advanced track ends, so it never lingers
    past the tour even if the client never sent the explicit clear request."""
    if track_id in ADVANCED_ONLY_TRACKS:
        from app.tutorial.demo import clear_demo_short
        clear_demo_short(current_user.id)


@tutorial_bp.route("/complete", methods=["POST"])
@login_required
def complete():
    """Mark a track completed (step index resets to 0)."""
    track_id = _json_body().get("track_id")
    _get_track_or_abort(track_id)
    if not complete_tutorial(current_user.id, track_id):
        abort(404)
    _end_advanced_cleanup(track_id)
    return jsonify({"ok": True})


@tutorial_bp.route("/dismiss", methods=["POST"])
@login_required
def dismiss():
    """Mark a track dismissed (step index resets to 0)."""
    track_id = _json_body().get("track_id")
    _get_track_or_abort(track_id)
    if not dismiss_tutorial(current_user.id, track_id):
        abort(404)
    _end_advanced_cleanup(track_id)
    return jsonify({"ok": True})


@tutorial_bp.route("/replay", methods=["POST"])
@login_required
def replay():
    """Start, resume, or restart a track.

    Body: {track_id, restart?: bool}
    - restart=true  -> always reset to step 0 ("Replay" / "Restart" button).
    - otherwise     -> resume an in-progress track at its saved step; start a
                       never-started track at 0; restart a finished track at 0.

    Returns the step the overlay should open at so the client's hand-off flag
    can match the server state.
    """
    body = _json_body()
    track_id = body.get("track_id")
    restart = body.get("restart") is True
    track = _get_track_or_abort(track_id)

    state = get_tutorial_state(current_user.id, track_id)
    if restart:
        # Force a fresh start from step 0, whatever the current status.
        create_or_update_tutorial_state(current_user.id, track_id, "in_progress", 0)
        index = 0
    elif state is None:
        create_or_update_tutorial_state(current_user.id, track_id, "in_progress", 0)
        index = 0
    elif state["status"] == "in_progress":
        index = state["current_step_index"]
    else:
        replay_tutorial(current_user.id, track_id)
        index = 0

    return jsonify({"ok": True, "redirect": _step_route(track, index), "step_index": index})


@tutorial_bp.route("/advanced/demo-short", methods=["POST"])
@login_required
def demo_short_open():
    """Open the Advanced tutorial's throwaway demo short (see app/tutorial/demo.py).

    Only while Advanced Mode is active. Returns ok:true with created:true/false;
    created:false (e.g. too little free cash) is not an error — the tour simply
    describes the feature instead of showing a live position.
    """
    from app.tutorial.demo import open_demo_short

    if not get_advanced_status(current_user.id)["active"]:
        return jsonify({"ok": False, "error": "Advanced Mode is not active"}), 409

    result = open_demo_short(current_user.id)
    return jsonify(result)


@tutorial_bp.route("/advanced/demo-clear", methods=["POST"])
@login_required
def demo_short_clear():
    """Remove the demo short, refunding the exact margin. Idempotent."""
    from app.tutorial.demo import clear_demo_short

    removed = clear_demo_short(current_user.id)
    return jsonify({"ok": True, "removed": removed})
