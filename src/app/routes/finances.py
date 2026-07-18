"""Finances routes: capital breakdown, fee burn, and cash runway."""

from flask import Blueprint, render_template, request
from flask_login import login_required, current_user

from app.decorators import advanced_required
from app.finances import get_finances_data

finances_bp = Blueprint('finances', __name__)


@finances_bp.route('/finances')
@login_required
@advanced_required
def overview():
    """Display the finances dashboard with capital and fee data."""
    data = get_finances_data(current_user.id)

    if request.headers.get('HX-Request'):
        return render_template('partials/finances_live.html', **data)

    return render_template('pages/finances.html', **data)
