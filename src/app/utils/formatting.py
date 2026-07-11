"""Number and currency formatting filters for Jinja2 templates."""


def format_currency(value):
    """Format a number as currency (e.g. $1,234.56)."""
    if value is None:
        return '$0.00'
    return f"${value:,.2f}"


def format_percentage(value):
    """Format a number as a percentage with sign (e.g. +12.34% or -5.67%)."""
    if value is None:
        return '0.00%'
    sign = '+' if value >= 0 else ''
    return f"{sign}{value:.2f}%"


def register_filters(app):
    """Register custom Jinja2 template filters."""
    app.jinja_env.filters['currency'] = format_currency
    app.jinja_env.filters['percentage'] = format_percentage
