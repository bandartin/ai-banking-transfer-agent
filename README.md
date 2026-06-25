# Banking AI Transfer Agent — Supervisor 멀티 에이전트 에디션

개인뱅킹 **자연어 이체** AI 에이전트 데모입니다.
으뜸은행 차세대 뱅킹 프로젝트에 **사전 제작(prebuilt) 에셋**으로 임포트할 수 있도록 설계되었으며,
LangGraph 1.x 의 최신 기능(Runtime, Send, Command, interrupt, Checkpointer, 노드 캐싱)과
A2A(Agent-to-Agent) 협업 구조를 실전 형태로 시연합니다.

---

## 아키텍처 — Supervisor 하이라키 멀티 에이전트

```
                      ┌──────────────────────────────────┐
   사용자 메시지 ────▶│   Supervisor (Leader) Agent       │◀── Runtime Context
                      │   · LLM Planning (rule 폴백)      │    (나이/등급/리스크/LLM)
                      │   · ExecutionPlan 구조화 출력      │
                      └───┬─────────┬─────────┬─────┬────┘
              Send(병렬)  │         │         │     │
                          ▼         ▼         ▼     ▼
                   ┌──────────┐ ┌─────────┐ ┌─────────┐ ┌──────────┐
                   │ Transfer │ │ Inquiry │ │Recommend│ │ Security │
                   │ 이체 실행 │ │잔액/내역 │ │  추천   │ │사기탐지   │
                   └────┬─────┘ └─────────┘ └─────────┘ └────▲─────┘
                        │      A2A 협업: 리스크 평가 의뢰      │
                        └─────────────────────────────────────┘
                          ▼
                      respond (집계 + 나이 맞춤 말투 합성)
```

- **Supervisor 가 계획(Plan)을 세우고**, 계획에 따라 하위 에이전트를 `Send` 로 **동적·병렬** 디스패치합니다.
  예: "잔고 보여주고 자주 보내는 사람도 추천해줘" → `inquiry` + `recommend` 병렬 실행 후 응답 합성.
- **TransferAgent ↔ SecurityAgent 협업**: 확인 카드를 띄우기 전에 Transfer 가 Security 서브그래프를
  직접 호출(A2A)하여 리스크 평가를 의뢰합니다. 심야 고액·낯선 수신자·단시간 다건·보안강화 고객
  룰에 따라 경고가 붙거나 OTP 가 강제됩니다.
- **확인 대기 중 새 요청** ("잔고 얼마지?") 이 오면 Transfer 가 `Command(graph=PARENT)` 로
  Supervisor 에 제어를 반납하고 재계획합니다 — 계층 간 핸드오프.
- 채팅 화면 우측의 **"Supervisor 실행 계획" / "에이전트 협업 타임라인"** 패널에서
  리더가 어떤 에이전트를 어떤 이유로 불렀는지 실시간으로 보입니다.

### 원칙: LLM은 이해·계획·표현만, 결정은 코드가

| 역할 | 담당 |
|------|------|
| 의도 분류 / 슬롯 추출 | LLM (키 없으면 결정론적 한국어 파서) |
| 실행 계획(어떤 에이전트를 부를지) | LLM 구조화 출력 (rule 플래너 폴백) |
| 응답 말투(나이 맞춤) | LLM 다듬기 + 결정론적 톤 보정 |
| 수신자 해석 / 호칭 학습 | 결정론적 Python + AliasMemory 테이블 |
| 잔액·한도 검증 / 리스크 룰 / 이체 실행 / 감사 로그 | **결정론적 Python — LLM 무관** |

LLM 이 이체 여부·금액·수신자를 결정하지 않습니다 (금융 컴플라이언스·감사 추적성).

---

## 적용된 LangGraph 1.x 최신 기능

| 기능 | 적용 위치 | 설명 |
|------|----------|------|
| **Runtime + `context_schema`** | `src/agents/context.py` | `BankingContext` 로 사용자/정책/LLM 의존성 주입 — 아래 학습 가이드 참고 |
| **`Send` API** | `supervisor/graph.py` | 계획 기반 동적 병렬 fan-out |
| **`Command(goto=)`** | `subagents/transfer.py` | 노드가 다음 노드를 동적으로 지목 |
| **`Command(graph=PARENT)`** | `subagents/transfer.py` | 서브그래프 → 부모(plan) 계층 간 핸드오프 |
| **`interrupt()` / `Command(resume=)`** | 되묻기·금액·확인·OTP | 정식 Human-in-the-Loop 멀티턴 (수동 플래그 제거) |
| **Checkpointer (`SqliteSaver`)** | `supervisor/graph.py` | thread_id(=세션)별 상태 영속화 — durable execution |
| **Subgraph 합성** | `subagents/*` | 각 에이전트가 독립 `StateGraph` → 상위 그래프 노드 |
| **노드 캐싱 (`CachePolicy`)** | `subagents/recommend.py` | 추천 계산을 사용자별 60초 캐시 |
| **Structured Output** | `supervisor/planner.py` | `ExecutionPlan` Pydantic 스키마 강제 |
| **A2A Agent Card** | `src/agents/a2a/` | 디스커버리 + JSON-RPC invoke 엔드포인트 |

---

## LangGraph Runtime 학습 가이드

이 프로젝트의 모든 노드는 `(state, runtime)` 시그니처를 사용합니다.

### State 와 Context 의 분리

| | State | Runtime Context |
|---|-------|----------------|
| 성격 | **가변** — 대화 중 노드가 읽고 갱신 | **불변** — 한 번의 invoke 동안 고정 |
| 예시 | intent, amount, 검증 결과 | user_id, 나이, LLM 설정, 수수료 정책 |
| 전달 | 노드 반환값으로 병합 | `graph.invoke(state, context=…)` 로 주입 |
| 체크포인트 | 저장됨 | 저장 안 됨 (매 호출 새로 주입) |

### 사용 패턴 (이 저장소의 실제 코드)

```python
from dataclasses import dataclass
from langgraph.graph import StateGraph
from langgraph.runtime import Runtime

@dataclass
class BankingContext:              # ① context_schema 정의 (src/agents/context.py)
    user_id: int
    age: int | None = None         #    → 나이 기반 맞춤 말투의 입력원
    llm_provider: str = "deterministic"
    otp_threshold: int = 3_000_000

def plan_node(state, runtime: Runtime[BankingContext]):   # ② 노드에서 접근
    ctx = runtime.context          #    타입 안전한 의존성 — current_app 불필요
    ...

graph = (
    StateGraph(BankingState, context_schema=BankingContext)  # ③ 그래프에 등록
    .add_node("plan", plan_node)
    ...
    .compile(checkpointer=SqliteSaver(conn))
)

graph.invoke(                       # ④ 호출 시 주입 — State 와 분리되어 전달
    fresh_turn_state(...),
    config={"configurable": {"thread_id": session_id}},
    context=BankingContext(user_id=1, age=30, ...),
)
```

### Runtime 이 이 프로젝트에서 해결한 문제 3가지

1. **Flask 결합 제거** — 노드가 `current_app.config` 대신 `runtime.context` 를 읽으므로
   에이전트 패키지가 웹 없이(A2A 단독 호출, 테스트, CLI) 동작합니다.
2. **Dynamic Prompting 의 입력원** — 나이/등급/리스크가 context 로 들어와
   플래너 프롬프트와 응답 말투가 상황에 따라 달라집니다.
3. **테스트 용이성** — `BankingContext(llm_provider="deterministic")` 주입만으로
   LLM 없는 결정론 경로를 강제할 수 있습니다.

---

## 호칭 학습 메모리 (세션을 넘는 기억)

사용자가 수신자를 부르는 표현은 계속 변합니다 — "여친", "여자친구", "내사랑"이
사실은 모두 **김서연**일 수 있습니다. 이를 `alias_memories` 테이블로 관리합니다.

```
1턴: "여친한테 2만원 보내줘"
  → 즐겨찾기에 '여친' 없음 → AI가 되묻기: "'여친'이 누구신지 아직 몰라요…"
2턴: "김서연"
  → 이체 확인 카드 + AliasMemory 에 (여친 → 김서연) 저장
─── 앱 재시작 / 새 세션 ───
"여친한테 5만원" → 즉시 김서연으로 해석 (사용 횟수 누적)
"내사랑한테 3만원" → 한 번 더 되묻고 학습 → 두 호칭 모두 김서연을 가리킴
```

- 같은 호칭이 **다른 사람으로 재지정되면 매핑이 갱신**됩니다 (호칭은 변한다).
- 동명이인("민수" 2명)도 한 번 선택하면 다음부터 **지난번 선택을 기억**해 즉시 해석합니다.
- 학습 현황은 **즐겨찾기 페이지의 "AI가 학습한 호칭"** 섹션과 DB 뷰어에서 확인됩니다.
- LangGraph Store 대신 RDB 를 쓰는 이유: 금융 도메인의 장기 기억은 감사 가능한
  정형 저장소에 두는 것이 컴플라이언스에 유리합니다.

---

## Dynamic Prompting — 나이 맞춤 말투

`BankingContext.age` 에서 톤 프로필이 결정되고, 프롬프트/응답이 동적으로 조립됩니다.

| 사용자 | 나이 | 톤 | 효과 |
|--------|------|----|------|
| 이병민 | 20대 | `young` | 간결, 가벼운 이모지 |
| 박준혁 | 30대 (VIP·보안강화) | `standard` | 표준 존댓말 + 보안 경고 강화, 100만원↑ OTP 강제 |
| 김은숙 | 60대 | `senior` | 금융용어 풀어쓰기("일일 한도(하루에 보낼 수 있는 최대 금액)"), 단계별 안내 |

- LLM 키가 있으면 `build_polish_prompt()` 가 톤 지침이 담긴 시스템 프롬프트로 응답을 다듬고,
- 키가 없어도 `apply_tone()` 의 결정론적 보정으로 동일한 정책이 적용됩니다.
- 채팅 화면 우상단 드롭다운으로 사용자를 전환해 비교 시연하세요.

---

## 목업 데이터 (개인뱅킹 한정)

앱 최초 실행 시 `seed.py` 가 자동 시드합니다. 법인/기업 수신자는 없습니다.

| 항목 | 규모 | 비고 |
|------|------|------|
| 사용자 | 3명 | 나이 30/68/39세 — 톤 비교, VIP·보안강화 프로필 |
| 계좌 | 6개 | 사용자별 주계좌+저축 |
| 수신자 | 27명 | 가족/친구/모임/집주인 등 전부 개인 관계 |
| 즐겨찾기 | 27건 | 동명이인 "민수" 2명 (모호성), "서연" (여친 학습 대상) |
| 이체내역 | **121건 / 6개월** | 월세·관리비·용돈 월별 반복 패턴 + 비정기 더치페이류 |
| 메모 | **약 10%만 채움** | 실제 앱 사용 패턴 반영 |
| 정기이체 | 9건 | 월세/관리비/용돈/적금/PT/모임회비 등 |
| 호칭 메모리 | 시드 1건 | 사용자3 "와이프"→최예린. 사용자1 "여친"은 **라이브 학습용으로 비움** |

### 주요 데모 사용자: 이병민 (kimcs, 20대)

주계좌 8,250,000원 — 일반 이체 / 잔액 부족(900만↑) / OTP(300만↑) 시나리오 커버.
주요 수신자: 엄마(이순자), 아빠, 민수×2(모호성), 집주인(장태호), 김서연(여친 학습),
룸메, 피티쌤, 동기모임, 할머니, 누나 등.

---

## 데모 시나리오 (카카오뱅크 AI이체 스타일 멀티턴)

```
A. 즐겨찾기 이체     "엄마에게 5만원 보내줘" → 확인 카드 → "확인" → ✅
B. 동명이인 되묻기   "민수에게 5만원" → 후보 2명 제시 → "1" → 확인 카드
                     (선택 결과가 학습되어 다음부터 즉시 해석)
C. 호칭 학습         "여친한테 2만원 보내줘" → "누구신지 몰라요" → "김서연"
                     → 새 세션에서도 '여친' 즉시 인식
D. 금액 되묻기       "지연한테 보내줘" → "얼마를 보내드릴까요?" → "3만원"
E. 확인 중 수정      확인 카드 상태에서 "아니 3만원으로 해줘" → 카드 갱신
F. 확인 중 새 요청   확인 카드 상태에서 "잔고 얼마지?" → 이체 보류·Supervisor 재계획
G. 병렬 fan-out      "잔고 보여주고 자주 보내는 사람도 추천해줘" → 2개 에이전트 동시 실행
H. OTP 협업          "집주인한테 400만원" → Security 평가 → 확인 → OTP(123456) → ✅
I. 자연어 메모       "지연한테 3만원 보내고 밥값이라고 적어줘" → 메모 자동 기입
J. 정기이체 추론     "월세 보내야 하지?" → 금액/수신자 자동 완성
K. 지난번처럼        "지난번처럼 보내줘" → 최근 이체 기반 확인 카드
L. 한글 수사 금액    "만원만 보내줘", "오만원", "삼십만원" 인식
M. 보안강화 고객     사용자3(박준혁)으로 "아버지한테 150만원" → 100만원↑ OTP 강제
N. 시니어 말투       사용자2(김은숙)로 "잔고 보여줘" → 용어 풀어쓰기 응답
```

---

## A2A (Agent-to-Agent) 표면

내부적으로는 LangGraph `Command`/`Send` 핸드오프로, 외부적으로는 표준 Agent Card 로 노출됩니다.

| 엔드포인트 | 설명 |
|-----------|------|
| `GET /.well-known/agent-card.json` | 대표 Agent Card (디스커버리) |
| `GET /api/a2a/agents` | 4개 Sub-Agent 카드 목록 |
| `POST /api/a2a/agents/<name>/invoke` | JSON-RPC `message/send` 스타일 원격 호출 |

```bash
# 앱 실행 후:
python scripts/a2a_client_demo.py
```

transfer 에이전트는 Human-in-the-Loop(확인/OTP)가 필요하므로 단독 invoke 가 차단되고
supervisor 경유로만 호출됩니다 — 금융 안전장치의 프로토콜 레벨 반영입니다.

---

## 빠른 시작

```bash
cd ai-banking-transfer-agent
python -m venv .venv
.venv\Scripts\activate            # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env               # 선택 (기본값으로도 실행 가능)
python app.py                      # http://localhost:8000
```

첫 실행 시 SQLite DB 생성 + 데모 데이터 자동 시드. 구버전 스키마가 감지되면 자동 재생성됩니다.

### LLM 모드 (선택)

기본 제공자는 OpenAI 이지만 **키가 없으면 자동으로 결정론적 한국어 파서로 폴백**하므로
키 없이 모든 기능이 동작합니다.

```bash
# .env
LLM_PROVIDER=openai
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-4o-mini
```

### 테스트

```bash
pytest tests/ -v                       # 44개 단위/통합 테스트
python scripts/smoke_test.py           # 13개 멀티턴 시나리오 E2E
python scripts/web_smoke.py            # 웹/A2A 레이어 검증
```

---

## AWX 이관/패키징 흐름

현재 저장소 루트의 `app.py`, `config.py`, `src/`, `templates/`, `static/`이 정본입니다.
AWX용 소스를 따로 손으로 복사해 관리하지 않고, `awx/`에는 실행 메타만 둔 뒤
필요할 때 `dist/awx-flow/` 산출물을 생성합니다.

```bash
# 정본 소스에서 AWX flow 산출물 생성
python scripts/build_awx_flow.py --clean

# 테스트까지 포함한 검증용 산출물
python scripts/build_awx_flow.py --clean --include-tests

# 로컬에서 AWX 실행 스크립트 확인
cd dist/awx-flow
bash run-application.sh
```

AWX 런타임에서는 `awx-bootstrap.json`과 `AWX_CREDENTIAL_*` 설정을 통해
Portal Credential을 우선 사용합니다. credential 조회가 실패하거나 SDK가 없는 로컬 환경에서는
기존 `OPENAI_API_KEY` 또는 결정론적 파서 경로로 폴백합니다.

주요 파일:

| 파일 | 설명 |
|------|------|
| `awx/run-application.sh` | AWX 표준 실행 진입점. Portal bootstrap 후 `opentelemetry-instrument`로 앱 실행 |
| `awx/awx-bootstrap.json` | Credential/external resource 사전 준비 manifest |
| `awx/pyproject.toml` | AWX flow 실행 의존성 |
| `scripts/build_awx_flow.py` | 정본 소스를 `dist/awx-flow/`로 조립하는 빌드 스크립트 |
| `src/awx_runtime/` | AWX credential, LLMLog, OTel, redaction optional 어댑터 |

실제 AWX workspace 업로드, `awx run`, `awx package`, 배포 후 검증 절차는
`docs/AWX_플랫폼_배포_실행_가이드.md`를 참고하세요.

---

## 페이지 설명

| 페이지 | URL | 설명 |
|--------|-----|------|
| 채팅 | `/chat` | 대화형 이체 + **Supervisor 계획/협업 타임라인 패널** + 사용자 전환 |
| 계좌/잔액 | `/accounts` | 계좌 목록, 잔액, 오늘의 이체 한도 |
| 즐겨찾기 | `/favorites` | 저장된 수신자 + **AI가 학습한 호칭** |
| 자동이체 | `/recurring` | 정기이체 목록 |
| 이체내역 | `/history` | 이체 기록 |
| 에이전트 로그 | `/agent-logs/` | 실행별 계획/협업 타임라인/노드 시간 |
| DB 뷰어 | `/admin/db-viewer` | 읽기 전용 테이블 탐색 (`alias_memories` 포함) |

---

## 패키지 구조

```
ai-banking-transfer-agent/
├── app.py / config.py / seed.py
├── docs/개발수행계획서.md
├── scripts/                       # smoke_test / web_smoke / a2a_client_demo
│
├── src/
│   ├── agents/
│   │   ├── context.py             # ★ BankingContext (Runtime context_schema)
│   │   ├── state.py               # BankingState (reducer 채널 — 병렬 안전)
│   │   ├── supervisor/            # Leader Agent
│   │   │   ├── graph.py           #   plan → Send fan-out → respond / 실행 진입점
│   │   │   ├── planner.py         #   ExecutionPlan (LLM 구조화 출력 + rule 폴백)
│   │   │   └── prompts.py         #   Dynamic Prompting (나이 톤 / 플래너 / 다듬기)
│   │   ├── subagents/
│   │   │   ├── transfer.py        #   interrupt 멀티턴 + 호칭 학습 + Security 협업
│   │   │   ├── inquiry.py         #   잔액/내역/자동이체 (읽기 전용)
│   │   │   ├── recommend.py       #   추천 (CachePolicy 노드 캐싱)
│   │   │   └── security.py        #   사기탐지 룰 (협업/단독 겸용)
│   │   ├── a2a/cards.py           #   Agent Card 정의
│   │   └── common/                #   schemas / parsing / llm / tracing / services
│   ├── models/database.py         # ORM (+ AliasMemory)
│   └── web/routes/                # Flask 블루프린트 (+ a2a.py)
│
├── templates/ · static/           # UI (협업 가시화 패널 포함)
└── tests/                         # pytest
```

---

## 향후 확장 경로

- **새 도메인 에이전트 추가**: `src/agents/subagents/loan.py` 를 만들고
  ① 서브그래프 노드로 등록, ② `a2a/cards.py` 에 카드 추가, ③ 플래너 매핑 한 줄 —
  LLM 플래너는 카드 설명만으로 새 에이전트를 디스패치합니다.
- **Slack 등 채널 어댑터**: `run_banking_agent(user_id, message, session_id)` 는
  Flask 요청에 의존하지 않으므로 어떤 이벤트 핸들러에서도 호출 가능합니다.
- **완전 분산 A2A**: 카드 스키마가 표준형이므로 `a2a-sdk` ASGI 서버로 각 에이전트를
  독립 배포해도 Supervisor 쪽은 클라이언트 전환만 하면 됩니다.

---

## 기술 스택

- **Python 3.11+** / **Flask 3** / **SQLAlchemy 2 + SQLite**
- **LangGraph 1.1** — Runtime · Send · Command · interrupt · SqliteSaver · CachePolicy
- **LangChain Core 1.x + langchain-openai** (선택, 폴백 내장)
- **Pydantic v2** / **Bootstrap 5** / **pytest**

## 문의

개선 사항이나 문의 사항이 있으시면 [qudals3579@korea.ac.kr](mailto:qudals3579@korea.ac.kr) 로 연락 부탁드립니다.
