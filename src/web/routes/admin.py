"""Admin / DB Viewer blueprint."""

from __future__ import annotations

import subprocess
import sys

from flask import Blueprint, current_app, jsonify, redirect, render_template, request, url_for
from sqlalchemy import inspect, text

from src.models.database import db

bp = Blueprint("admin", __name__, url_prefix="/admin")

# Tables exposed in the DB viewer (keep read-only for safety)
VIEWABLE_TABLES = [
    "users",
    "accounts",
    "recipients",
    "favorites",
    "recurring_transfers",
    "transfer_history",
    "transfer_limits",
    "chat_sessions",
    "chat_messages",
    "audit_logs",
]


@bp.route("/db-viewer")
def db_viewer():
    table = request.args.get("table", "accounts")
    search = request.args.get("search", "").strip()

    if table not in VIEWABLE_TABLES:
        table = "accounts"

    # Get columns
    inspector = inspect(db.engine)
    columns = [c["name"] for c in inspector.get_columns(table)]

    # Build query
    if search and columns:
        # Simple full-scan filter on all text columns
        conditions = " OR ".join(
            f"CAST({col} AS TEXT) LIKE :search" for col in columns
        )
        count_q = text(f"SELECT COUNT(*) FROM {table} WHERE {conditions}")
        data_q = text(f"SELECT * FROM {table} WHERE {conditions} LIMIT 200")
        params = {"search": f"%{search}%"}
    else:
        count_q = text(f"SELECT COUNT(*) FROM {table}")
        data_q = text(f"SELECT * FROM {table} LIMIT 200")
        params = {}

    with db.engine.connect() as conn:
        total = conn.execute(count_q, params).scalar()
        rows = conn.execute(data_q, params).fetchall()

    return render_template(
        "admin.html",
        tables=VIEWABLE_TABLES,
        selected_table=table,
        columns=columns,
        rows=[list(r) for r in rows],
        total=total,
        search=search,
    )


@bp.route("/reset-demo", methods=["POST"])
def reset_demo():
    """Drop all tables, recreate, and reseed demo data."""
    try:
        db.drop_all()
        db.create_all()
        # Run seed script in-process
        import seed  # type: ignore
        seed.run()
        return jsonify({"status": "ok", "message": "데모 데이터가 초기화되었습니다."})
    except Exception as exc:
        current_app.logger.exception("Reset failed")
        return jsonify({"status": "error", "message": str(exc)}), 500
