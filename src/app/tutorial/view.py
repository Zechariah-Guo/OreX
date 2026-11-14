"""Presentation logic for the tutorial list on the Help page."""

from app.tutorial.data import ADVANCED_ONLY_TRACKS

STATUS_LABELS = {
    'not_started': 'Not started',
    'in_progress': 'In progress',
    'completed': 'Completed',
    'dismissed': 'Skipped',
}

# Finished tracks offer "Replay" (restart at step 0); an in-progress track offers
# "Resume" (continue from the saved step). Both use the /tutorial/replay endpoint,
# which no-ops an in-progress track and returns its current step. Only a brand-new
# "not_started" track has no button (it will auto-trigger on its own).
REPLAYABLE_STATUSES = frozenset({'completed', 'dismissed'})


def build_tutorial_list(tracks, states, advanced_purchased, advanced_active=False):
    """Build the rows shown in the Help page "Tutorials" section.

    Args:
        tracks: track metadata dicts (id, name, trigger), in display order.
        states: the player's tutorial_progress rows as dicts.
        advanced_purchased: whether the player has ever purchased Advanced Mode.
        advanced_active: whether Advanced Mode is currently switched on.

    Rules: every player sees the Beginner tutorial; Advanced-only tracks are
    listed only once Advanced Mode has been purchased (whether or not it is
    currently active). A completed/skipped track shows "Replay"; an in-progress
    track shows "Resume" so a player who dismissed the resume toast always has a
    way back in.

    Mode gating: each track spotlights UI that only exists in one mode, so its
    buttons are shown but disabled unless the player is in that mode. The
    Advanced tutorial needs Advanced Mode ON; the Beginner tutorial needs it OFF
    (its steps target the standard trade panel, which the Advanced layout
    replaces). The player switches mode in Settings themselves — we never
    auto-switch, because the toggle has a cooldown and is blocked while shorts
    are open.
    """
    status_by_track = {s['track_id']: s['status'] for s in states}
    rows = []
    for track in tracks:
        advanced_only = track['id'] in ADVANCED_ONLY_TRACKS
        if advanced_only and not advanced_purchased:
            continue
        status = status_by_track.get(track['id'], 'not_started')
        # Gate each track to the mode its steps are built for.
        if advanced_only:
            disabled = not advanced_active
            reason = 'Turn on Advanced Mode in Settings to take this tutorial.'
        else:
            disabled = advanced_active
            reason = 'Turn off Advanced Mode in Settings to take this tutorial.'
        rows.append({
            'id': track['id'],
            'name': track['name'],
            'status': status,
            'status_label': STATUS_LABELS.get(status, status),
            'actions': _actions_for(status),
            'can_replay': status in REPLAYABLE_STATUSES or status == 'in_progress',
            'disabled': disabled,
            'disabled_reason': reason if disabled else None,
            'advanced_only': advanced_only,
        })
    return rows


# Each action becomes a button: its label and whether it forces a restart at step 0.
# 'resume' continues from the saved step; 'replay' restarts.
_RESUME = {'id': 'resume', 'label': 'Resume', 'restart': False}
_REPLAY = {'id': 'replay', 'label': 'Replay', 'restart': True}


def _actions_for(status):
    """Buttons to show for a track in the given status.

    In progress -> Resume (continue) + Replay (restart). Finished -> Replay only.
    Not started -> none (it will auto-trigger on its own).
    """
    if status == 'in_progress':
        return [_RESUME, _REPLAY]
    if status in REPLAYABLE_STATUSES:
        return [_REPLAY]
    return []
