from flask import Blueprint, current_app, render_template
from src.models.database import db, RecurringTransfer, Favorite, Recipient

bp = Blueprint("recurring", __name__)


@bp.route("/recurring")
def recurring():
    user_id = current_app.config["DEMO_USER_ID"]

    rts = (
        db.session.query(RecurringTransfer)
        .filter(RecurringTransfer.user_id == user_id)
        .order_by(RecurringTransfer.day_of_month.asc())
        .all()
    )

    rows = []
    for rt in rts:
        recipient_name = None
        bank_name = None
        account_number = None
        if rt.favorite and rt.favorite.recipient:
            r: Recipient = rt.favorite.recipient
            recipient_name = r.name
            bank_name = r.bank_name
            account_number = r.account_number

        rows.append({
            "id": rt.id,
            "alias": rt.alias,
            "recipient_name": recipient_name,
            "bank_name": bank_name,
            "account_number": account_number,
            "default_amount": rt.default_amount,
            "recurrence_type": rt.recurrence_type,
            "day_of_month": rt.day_of_month,
            "next_due_date": rt.next_due_date,
            "is_active": rt.is_active,
            "memo": rt.memo,
        })

    return render_template("recurring.html", rows=rows)
