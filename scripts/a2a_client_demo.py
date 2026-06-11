"""
A2A 클라이언트 데모 — 외부 에이전트 입장에서 우리 에이전트를 발견/호출한다.

사용법:
  1. 다른 터미널에서 앱 실행:  python app.py
  2. 이 스크립트 실행:        python scripts/a2a_client_demo.py

흐름 (A2A 프로토콜의 핵심 3단계):
  ① Discovery — /.well-known/agent-card.json 에서 Agent Card 조회
  ② Card 검사 — 각 Sub-Agent 의 스킬 확인
  ③ Invoke   — JSON-RPC message/send 로 원격 호출
"""

import json
import sys
import urllib.request

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000"


def get(url):
    with urllib.request.urlopen(url) as r:
        return json.loads(r.read().decode("utf-8"))


def post(url, body):
    req = urllib.request.Request(
        url, data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST",
    )
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read().decode("utf-8"))


def main():
    print(f"① Discovery — {BASE}/.well-known/agent-card.json")
    card = get(f"{BASE}/.well-known/agent-card.json")
    print(f"   에이전트: {card['name']}")
    print(f"   스킬 {len(card['skills'])}개, 하위 에이전트 {len(card['subAgents'])}개\n")

    print("② Agent Cards")
    agents = get(f"{BASE}/api/a2a/agents")
    for key, c in agents.items():
        skills = ", ".join(s["id"] for s in c["skills"])
        print(f"   - {key:10s} {c['name']:16s} 스킬: {skills}")
    print()

    print("③ Invoke — InquiryAgent 에 잔액 조회 의뢰")
    resp = post(f"{BASE}/api/a2a/agents/inquiry/invoke", {
        "jsonrpc": "2.0", "id": "demo-1", "method": "message/send",
        "params": {
            "message": {"parts": [{"text": "잔고 알려줘"}]},
            "metadata": {"user_id": 1, "sub_intent": "balance"},
        },
    })
    text = resp["result"]["artifacts"][0]["parts"][0]["text"]
    print("   " + text.replace("\n", "\n   "))
    print()

    print("③' Invoke — SecurityAgent 보안 리포트")
    resp = post(f"{BASE}/api/a2a/agents/security/invoke", {
        "jsonrpc": "2.0", "id": "demo-2", "method": "message/send",
        "params": {
            "message": {"parts": [{"text": "보안 점검"}]},
            "metadata": {"user_id": 3, "sub_intent": "report"},
        },
    })
    text = resp["result"]["artifacts"][0]["parts"][0]["text"]
    print("   " + text.replace("\n", "\n   "))

    print("\n✅ A2A 디스커버리/호출 데모 완료")


if __name__ == "__main__":
    main()
