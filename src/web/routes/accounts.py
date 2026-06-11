from flask import Blueprint, current_app, render_template
from src.agents.common.services.balance_service import get_balance_summary

bp = Blueprint("accounts", __name__)


@bp.route("/accounts")
def accounts():
    from src.web.routes.chat import current_user_id
    user_id = current_user_id()
    summary = get_balance_summary(user_id)
    return render_template("accounts.html", summary=summary)


