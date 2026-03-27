from flask import Blueprint, current_app, render_template, request
from src.models.database import db, TransferHistory, Recipient, Account

bp = Blueprint("history", __name__)


@bp.route("/history")
def history():
    user_id = current_app.config["DEMO_USER_ID"]
    page = request.args.get("page", 1, type=int)
    per_page = 20
    status_filter = request.args.get("status", "")

    query = (
        db.session.query(TransferHistory)
        .filter(TransferHistory.user_id == user_id)
        .order_by(TransferHistory.transferred_at.desc())
    )

    if status_filter:
        query = query.filter(TransferHistory.status == status_filter)

    total = query.count()
    records = query.offset((page - 1) * per_page).limit(per_page).all()

    rows = []
    for r in records:
        rec: Recipient = r.recipient
        acc: Account = r.source_account
        alias = r.favorite.alias if r.favorite else rec.name
        rows.append({
            "id": r.id,
            "transferred_at": r.transferred_at,
            "source_account": acc.account_name if acc else "—",
            "alias": alias,
            "name": rec.name,
            "bank": rec.bank_name,
            "account": rec.account_number,
            "amount": r.amount,
            "fee": r.fee,
            "total": r.amount + r.fee,
            "memo": r.memo,
            "status": r.status,
        })

    total_pages = (total + per_page - 1) // per_page

    return render_template(
        "history.html",
        rows=rows,
        page=page,
        total_pages=total_pages,
        total=total,
        status_filter=status_filter,
    )
