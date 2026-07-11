"""Transaction history route with pagination."""

from flask import Blueprint, render_template, request
from flask_login import login_required, current_user

from app.models import get_transactions_paginated

history_bp = Blueprint('history', __name__)

PER_PAGE = 20


@history_bp.route('/history')
@login_required
def overview():
    """Paginated transaction history."""
    page = request.args.get('page', 1, type=int)
    show_archived = request.args.get('archived', '0') == '1'

    if page < 1:
        page = 1

    transactions, total_count = get_transactions_paginated(
        current_user.id, page=page, per_page=PER_PAGE, show_archived=show_archived
    )

    total_pages = max(1, (total_count + PER_PAGE - 1) // PER_PAGE)

    return render_template('pages/history.html',
                           transactions=transactions,
                           page=page,
                           total_pages=total_pages,
                           total_count=total_count,
                           show_archived=show_archived)
