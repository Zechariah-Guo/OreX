"""Leaderboard route: ranked users by total portfolio value."""

from flask import Blueprint, render_template, request
from flask_login import login_required, current_user

from app.models import get_leaderboard

leaderboard_bp = Blueprint('leaderboard', __name__)


@leaderboard_bp.route('/leaderboard')
@login_required
def overview():
    """Display the leaderboard ranked by total value."""
    rankings = get_leaderboard()

    # HTMX partial: return only the table body
    if request.headers.get('HX-Request'):
        return render_template('partials/leaderboard_table.html',
                               rankings=rankings,
                               current_user_id=current_user.id)

    return render_template('pages/leaderboard.html',
                           rankings=rankings,
                           current_user_id=current_user.id)
