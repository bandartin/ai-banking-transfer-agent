"""웹 레이어 스모크 — 템플릿 렌더링 / 채팅 API / A2A 엔드포인트."""

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
os.environ["LANGCHAIN_TRACING_V2"] = "false"

from app import create_app
from config import Config


class WebSmokeConfig(Config):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    LLM_PROVIDER = "deterministic"
    CHECKPOINT_DB_PATH = ":memory:"
    LANGSMITH_ENABLED = False


def main():
    from src.agents.supervisor.graph import reset_graph_singleton
    reset_graph_singleton()

    app = create_app(WebSmokeConfig)
    with app.app_context():
        import seed
        seed.run(app)

    c = app.test_client()

    # 페이지 렌더링
    for url in ["/chat", "/accounts", "/favorites", "/recurring", "/history",
                "/agent-logs/", "/admin/db-viewer?table=alias_memories"]:
        r = c.get(url)
        assert r.status_code == 200, f"{url} -> {r.status_code}"
        print(f"OK  GET {url}")

    # 채팅 API (이체 확인 → 확인)
    r = c.post("/api/chat/message", json={"message": "엄마한테 5만원 보내줘"})
    d = r.get_json()
    assert r.status_code == 200 and d["pending_state"] == "awaiting_confirmation", d
    assert d["plan"]["steps"][0]["agent"] == "transfer"
    print("OK  POST /api/chat/message (confirmation)")

    r = c.post("/api/chat/message", json={"message": "확인"})
    d = r.get_json()
    assert d["response_type"] == "success", d["response_type"]
    assert any(a["event"] == "security_consult" for a in d["agent_activity"])
    print("OK  POST /api/chat/message (success + collaboration activity)")

    # 실행 로그 상세 페이지
    r = c.get(f"/agent-logs/{d['run_log_id']}")
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    assert "Supervisor 실행 계획" in html and "협업 타임라인" in html
    print("OK  GET /agent-logs/<id> (plan + activity rendered)")

    # 사용자 전환
    r = c.post("/api/chat/user", json={"user_id": 2})
    assert r.get_json()["display_name"] == "김은숙"
    print("OK  POST /api/chat/user")

    # A2A discovery + invoke
    r = c.get("/.well-known/agent-card.json")
    assert r.status_code == 200 and "subAgents" in r.get_json()
    print("OK  GET /.well-known/agent-card.json")

    r = c.get("/api/a2a/agents")
    assert set(r.get_json().keys()) == {"transfer", "inquiry", "recommend", "security"}
    print("OK  GET /api/a2a/agents")

    r = c.post("/api/a2a/agents/inquiry/invoke", json={
        "jsonrpc": "2.0", "id": "1", "method": "message/send",
        "params": {"message": {"parts": [{"text": "잔고"}]},
                   "metadata": {"user_id": 1, "sub_intent": "balance"}},
    })
    d = r.get_json()
    text = d["result"]["artifacts"][0]["parts"][0]["text"]
    assert "잔액" in text, text
    print("OK  POST /api/a2a/agents/inquiry/invoke")

    r = c.post("/api/a2a/agents/transfer/invoke", json={
        "jsonrpc": "2.0", "id": "2", "method": "message/send",
        "params": {"message": {"parts": [{"text": "5만원 보내줘"}]}},
    })
    assert r.status_code == 400  # HITL 필요 → supervisor 경유 안내
    print("OK  POST /api/a2a/agents/transfer/invoke (HITL guard)")

    print("\n✅ 웹 스모크 전부 통과!")


if __name__ == "__main__":
    main()
