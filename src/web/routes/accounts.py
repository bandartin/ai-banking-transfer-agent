from flask import Blueprint, current_app, render_template
from src.agents.transfer_agent.services.balance_service import get_balance_summary

bp = Blueprint("accounts", __name__)


@bp.route("/accounts")
def accounts():
    user_id = current_app.config["DEMO_USER_ID"]
    summary = get_balance_summary(user_id)
    return render_template("accounts.html", summary=summary)
