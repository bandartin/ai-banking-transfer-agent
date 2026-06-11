from flask import Blueprint, render_template
from src.models.database import db, Favorite, Recipient
from src.agents.common.services.recommendation_service import get_recommendations
from src.agents.common.services.alias_service import list_for_user
from src.web.routes.chat import current_user_id

bp = Blueprint("favorites", __name__)


@bp.route("/favorites")
def favorites():
    user_id = current_user_id()

    favs = (
        db.session.query(Favorite)
        .filter(Favorite.user_id == user_id)
        .order_by(Favorite.send_count.desc(), Favorite.last_sent_at.desc())
        .all()
    )

    recommendations = get_recommendations(user_id)
    rec_map = {r.alias: r for r in recommendations}

    rows = []
    for f in favs:
        r: Recipient = f.recipient
        rows.append({
            "id": f.id,
            "alias": f.alias,
            "name": r.name,
            "bank": r.bank_name,
            "account": r.account_number,
            "is_favorite": f.is_favorite,
            "send_count": f.send_count,
            "last_sent_at": f.last_sent_at,
            "score": rec_map[f.alias].score if f.alias in rec_map else None,
            "rank": rec_map[f.alias].rank if f.alias in rec_map else None,
        })

    # 에이전트가 되묻기로 학습한 호칭 (여친 → 김서연 …)
    learned_aliases = list_for_user(user_id)

    return render_template("favorites.html", rows=rows, learned_aliases=learned_aliases)
