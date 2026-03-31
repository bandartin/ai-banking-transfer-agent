"""
Prebuilt Banking AI Transfer Agent — Flask application entry point.

Run:
    python app.py
    # or
    flask --app app run
"""

import os
import sys
from pathlib import Path

# Ensure project root is on sys.path so `src` and `seed` are importable
sys.path.insert(0, str(Path(__file__).parent))

from flask import Flask
from config import Config
from src.models.database import init_db
from src.web.routes import register_routes


def create_app(config_class=Config) -> Flask:
    """Application factory."""
    app = Flask(
        __name__,
        template_folder="templates",
        static_folder="static",
    )
    app.config.from_object(config_class)

    # Initialise database (creates tables if they don't exist)
    init_db(app)

    # Register all blueprints
    register_routes(app)

    return app


if __name__ == "__main__":
    app = create_app()

    # Auto-seed if the database is empty
    with app.app_context():
        from src.models.database import db, User
        if db.session.query(User).count() == 0:
            print("[DB] Database is empty. Seeding sample data...")
            import seed
            seed.run(app)

    port = app.config.get("PORT", 5000)
    ls_status = (
        f"[LangSmith] Enabled (project: {app.config['LANGSMITH_PROJECT']})"
        if app.config.get("LANGSMITH_ENABLED")
        else "[LangSmith] Disabled (enable with LANGCHAIN_TRACING_V2=true)"
    )
    print(f"\n[APP] AI Transfer Assistant - http://localhost:{port}")
    print(f"[STATUS] {ls_status}\n")
    app.run(debug=app.config.get("DEBUG", True), port=port, host="0.0.0.0")
