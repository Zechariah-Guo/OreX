"""Blueprint registration for OreX."""


def register_blueprints(app):
    """Register all application blueprints."""
    from app.routes.auth import auth_bp
    from app.routes.dashboard import dashboard_bp
    from app.routes.market import market_bp
    from app.routes.trade import trade_bp
    from app.routes.portfolio import portfolio_bp
    from app.routes.history import history_bp
    from app.routes.settings import settings_bp
    from app.routes.leaderboard import leaderboard_bp
    from app.routes.pages import pages_bp
    from app.routes.two_factor import two_factor_bp

    app.register_blueprint(pages_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(market_bp)
    app.register_blueprint(trade_bp)
    app.register_blueprint(portfolio_bp)
    app.register_blueprint(history_bp)
    app.register_blueprint(settings_bp)
    app.register_blueprint(leaderboard_bp)
    app.register_blueprint(two_factor_bp)
