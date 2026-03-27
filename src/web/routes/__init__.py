"""Register all Flask blueprints."""

from .chat import bp as chat_bp
from .accounts import bp as accounts_bp
from .favorites import bp as favorites_bp
from .recurring import bp as recurring_bp
from .history import bp as history_bp
from .admin import bp as admin_bp
from .agent_logs import bp as agent_logs_bp


def register_routes(app):
    app.register_blueprint(chat_bp)
    app.register_blueprint(accounts_bp)
    app.register_blueprint(favorites_bp)
    app.register_blueprint(recurring_bp)
    app.register_blueprint(history_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(agent_logs_bp)
