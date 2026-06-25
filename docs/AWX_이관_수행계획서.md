# AgenticWorks(AWX) 프로그램 이관 수행계획서

> 작성일: 2026-06-22  
> 대상 저장소: `ai-banking-transfer-agent`  
> 참조 원본: `docs/awx_jupyter_initial_setup_20260506`  
> 목표: 현재 AI 이체 서비스 전체 코드를 AWX 개발·배포 표준에 맞게 안정적으로 이관

---

## 1. 목적 및 결론

현재 AI 이체 서비스는 이미 LangGraph 기반 Supervisor/Sub-Agent 구조, Runtime context, `Send`, `Command`, `interrupt`, `SqliteSaver` 체크포인터, 로컬 실행 로그를 갖추고 있다. 따라서 이번 AWX 이관의 핵심은 에이전트 로직을 다시 만드는 것이 아니라, 다음 네 가지 경계를 AWX 표준으로 정렬하는 것이다.

1. **실행·패키징 경계**: AWX `flow/` 실행 단위, `run-application.sh`, `awx run`, `awx package` 기준으로 배포 가능하게 구성한다.
2. **LLM 호출 경계**: `.env`의 `OPENAI_API_KEY` 직접 의존을 줄이고 `awx.resources.Credential.get(...)` 및 `bootstrap_portal_runtime(...)`으로 credential/resource를 해석한다.
3. **관측·로그 경계**: 현재 DB 기반 `AgentRunLog`는 감사/화면용으로 유지하고, AWX SDK의 `Tracer`, `LLMLog`, 필요 시 `Metering`, OpenTelemetry 자동 계측을 추가한다.
4. **HITL trace 경계**: Flask 요청이 여러 번으로 끊기는 `interrupt`/`resume` 흐름을 AWX trace에서 하나의 업무 흐름으로 추적할 수 있도록 trace context 저장·복원 패턴을 도입한다.

권고 이관 방식은 **기능 보존형 단계 이관**이다. 먼저 현행 Flask/LangGraph 앱을 AWX `flow` 표준으로 감싸고, 그 다음 SDK credential·observability를 얇은 어댑터로 붙인다. FastAPI 전환이나 DB 외부화는 AWX 구동 성공 후 별도 안정화 단계에서 수행한다.

---

## 2. 참조한 AWX 원본과 적용 포인트

| 참조 파일 | 확인 내용 | 현 서비스 적용 방향 |
|---|---|---|
| `docs/awx_jupyter_initial_setup_20260506/AWX_QUICKSTART.md` | `flow/` workspace에서 `awx run`, `awx package` 수행 | 저장소에 배포용 `flow/`를 만들고 `run-application.sh`를 표준 진입점으로 둔다. |
| `docs/awx_jupyter_initial_setup_20260506/flow/README.md` | `example_sdk`, `example_app`, `make init/sync/run`, OTel endpoint는 SDK 자동 감지 권장 | 로컬 개발과 AWX 배포 실행 스크립트를 분리하되, OTLP endpoint 직접 하드코딩은 금지한다. |
| `flow/example_sdk/example_resources/credentials_example.py` | `Credential.get(service_id, provider_alias, service_type_name)`로 credential 조회 | `OPENAI_API_KEY` 직접 주입 대신 AWX credential 조회를 1순위로 사용한다. |
| `flow/example_sdk/example_resources/portal_bootstrap_example.py` | `bootstrap_portal_runtime(...)`으로 credential/resource/prompt/MCP cache 준비 | 앱 startup 또는 launcher에서 필요한 credential/external resource를 사전 준비한다. |
| `flow/example_sdk/example_observability/telemetry_example.py` | `Tracer.trace(...)`, span attribute/event/metric 사용 | LangGraph turn, node, LLM 호출, 이체 실행 단위에 AWX span을 추가한다. |
| `flow/example_sdk/example_observability/llm_log_example.py` | `LLMLog.log(LogInput(...))`로 LLM 입출력·토큰·시간 로그 적재 | `src/agents/common/llm.py`의 세 LLM 호출에 공통 로깅 래퍼를 적용한다. |
| `flow/example_sdk/example_resources/full_llm_app_example.py` | Logger, Credential, Guardrail, Metering, LLMLog를 한 흐름으로 연결 | SDK import 실패 시 graceful fallback하되, AWX 런타임에서는 SDK 경로를 기본으로 한다. |
| `flow/example_app/fastapi-observability-auto/client/README.md` | `opentelemetry-instrument`, `instrument_app`, `X-AWX-*` 헤더, eval/otel 응답 제어 | Flask 유지 시 `opentelemetry-instrument`와 수동 span을 우선 적용하고, FastAPI 전환은 후속 검토한다. |
| `flow/example_app/langgraph-hitl-auto/README.md` 및 `chat_runtime.py` | `interrupt()`/`Command(resume=...)`를 같은 trace로 묶기 위해 trace carrier 저장·복원 | `ChatSession` 또는 별도 runtime table에 trace carrier를 저장해 HITL resume trace를 연결한다. |

---

## 3. 현재 코드 검토 결과

### 3.1 현행 구조

- 진입점: `app.py`의 Flask application factory와 `python app.py` 실행.
- 설정: `config.py`에서 `.env` 기반 `OPENAI_API_KEY`, `OPENAI_MODEL`, `LANGCHAIN_*`, SQLite 경로를 읽는다.
- 에이전트 진입점: `src/agents/supervisor/graph.py`의 `run_banking_agent(...)`.
- LLM 호출: `src/agents/common/llm.py`에서 `langchain_openai.ChatOpenAI` 직접 생성.
- 상태 영속화: `SqliteSaver` 체크포인트 DB와 `ChatSession`/`ChatMessage`/`AgentRunLog` ORM 병행.
- 관측성: `src/agents/common/tracing.py`의 상태 누적 로그, 선택적 LangSmith tracing, DB `AgentRunLog`.
- 테스트: `tests/test_agent.py`, `tests/test_transfer_service.py`, `tests/test_parsing.py` 등 결정론 폴백 중심 회귀 테스트가 존재한다.

### 3.2 AWX 기준 차이점

| 영역 | 현재 | AWX 기준 TO-BE |
|---|---|---|
| 실행 단위 | 저장소 루트에서 `python app.py` | `flow/run-application.sh`를 통해 AWX가 실행 |
| 의존성 | `requirements.txt` + venv | `flow/pyproject.toml`/`uv`, AWX SDK는 런타임 제공 또는 bootstrap |
| Secret | `.env`의 `OPENAI_API_KEY` | `awx.resources.Credential.get(...)` |
| 리소스 bootstrap | 없음 | `awx-bootstrap.json` + `bootstrap_portal_runtime(...)` |
| LLM 로그 | LangSmith 선택 + 로컬 DB | AWX `LLMLog`, `Metering`, OTel span |
| 앱 로그 | Flask logger, DB 로그 | `awx.core.Logger` + 기존 로컬 감사 로그 |
| trace | 한 HTTP 요청 단위 중심 | HITL resume 포함 업무 흐름 trace |
| 배포 검증 | pytest/smoke | `awx run` 성공, `awx package` 가능, collector 전송 확인 |

### 3.3 보존해야 할 원칙

- **LLM은 이해·계획·표현까지만 사용**하고, 금액·한도·잔액·수신자 확정·이체 실행은 결정론 코드가 담당한다.
- `AgentRunLog`와 `AuditLog`는 화면/감사용 로컬 근거이므로 제거하지 않는다.
- 키가 없거나 AWX credential 조회가 실패해도 테스트와 데모는 결정론 폴백으로 동작해야 한다.
- 금융 민감정보는 AWX 외부 로그에 그대로 싣지 않는다. 원문 감사가 필요하면 로컬 DB에 제한적으로 보관하고, AWX LLMLog/OTel에는 마스킹본을 기본 전송한다.

---

## 4. 목표 아키텍처

```text
AWX runtime
  |
  | awx run / awx package
  v
flow/run-application.sh
  |
  | bootstrap_portal_runtime + opentelemetry-instrument
  v
Flask app.py
  |
  | request/session
  v
run_banking_agent(user_id, message, session_id)
  |
  +-- AWX Tracer span: banking.turn
  +-- LangGraph Supervisor/Sub-Agent graph
  |     +-- node spans: supervisor.plan, transfer.extract, ...
  |     +-- LLM wrapper: Credential -> ChatOpenAI -> LLMLog/Metering
  |     +-- deterministic banking services
  |
  +-- local DB: ChatMessage, AgentRunLog, AuditLog
  +-- AWX OTel/LLMLog/Metering: redacted observability payload
```

### 4.1 정본 유지 및 배포 산출물 목표

정본은 저장소 루트의 현재 코드(`app.py`, `config.py`, `src/`, `templates/`, `static/`)로 유지한다. AWX 전용 디렉토리에 코드를 수작업 복제하지 않고, `awx/`에는 실행 메타만 둔 뒤 빌드 스크립트가 패키징 산출물을 생성한다.

정본/메타/산출물의 역할은 다음과 같이 분리한다.

```text
ai-banking-transfer-agent/
├── app.py / config.py / seed.py
├── src/ / templates/ / static/        # 현재 코드 정본
├── awx/                               # AWX 실행 메타
│   ├── run-application.sh
│   ├── awx-bootstrap.json
│   ├── pyproject.toml
│   └── README.md
├── scripts/
│   └── build_awx_flow.py              # 정본 기반 산출물 조립
└── dist/awx-flow/                     # 생성 산출물(.gitignore)
```

AWX 패키징 대상 산출물은 `dist/awx-flow/` 아래에 완결된 실행 소스로 생성한다.

```text
dist/awx-flow/
├── run-application.sh
├── pyproject.toml
├── awx-bootstrap.json
├── app.py
├── config.py
├── seed.py
├── src/
├── static/
├── templates/
└── tests/
```

AWX 런타임이 반드시 디렉토리명을 `flow/`로 요구할 경우에는 `scripts/build_awx_flow.py --output flow --clean`으로 같은 산출물을 만들 수 있다. 이 경우에도 `flow/`는 생성 산출물이며 정본은 아니다.

### 4.2 신규/수정 모듈 제안

| 파일 | 역할 |
|---|---|
| `awx/run-application.sh` | AWX 표준 실행 진입점. SDK bootstrap, env default, `opentelemetry-instrument` 실행 담당. |
| `awx/awx-bootstrap.json` | credential/external resource bootstrap manifest. |
| `awx/pyproject.toml` | AWX flow 의존성 정의. |
| `scripts/build_awx_flow.py` | 정본 소스를 `dist/awx-flow/`로 조립하는 빌드 스크립트. |
| `src/awx_runtime/__init__.py` | AWX 연동 모듈 namespace. |
| `src/awx_runtime/config.py` | AWX credential service id, provider alias, service type, redaction 정책. |
| `src/awx_runtime/credentials.py` | `Credential.get(...)` 래퍼와 `OPENAI_API_KEY` local fallback. |
| `src/awx_runtime/observability.py` | `Logger`, `Tracer`, `LLMLog`, `Metering` 래퍼. SDK 미존재 시 no-op. |
| `src/awx_runtime/redaction.py` | 계좌번호, 전화번호, API key, 주민성 정보, 금액/수신자 정책별 마스킹. |
| `src/awx_runtime/trace_context.py` | HITL resume용 trace carrier 저장·복원 유틸. |

---

## 5. 핵심 개발 방안

### 5.1 LLM 호출 방식 이관

현재 `src/agents/common/llm.py`의 `get_chat_model(ctx, temperature)`는 `ctx.openai_api_key`를 직접 넘긴다. 이를 다음 순서로 변경한다.

1. `BankingContext`에 AWX credential 메타데이터를 추가한다.
   - `llm_provider`
   - `openai_model`
   - `awx_credential_service_id`
   - `awx_provider_alias`
   - `awx_service_type_name`
   - `awx_credential_id` 또는 조회 결과 metadata
2. `build_context(...)`에서 `OPENAI_API_KEY`를 직접 주입하기 전에 AWX credential resolver를 호출한다.
3. resolver 순서는 다음과 같이 둔다.
   - 1순위: `awx.resources.Credential.get(...)`
   - 2순위: AWX runtime cache/bootstrap 결과
   - 3순위: 로컬 개발용 `OPENAI_API_KEY`
   - 실패: 기존처럼 deterministic fallback
4. `extract_slots`, `plan_with_llm`, `polish_response`는 LLM 호출 전후를 공통 래퍼로 감싼다.
   - 시작/종료 시간
   - 모델명
   - 호출 목적: `slot_extraction`, `supervisor_planning`, `response_polish`
   - 성공/실패 상태
   - 토큰 사용량이 response metadata에 있으면 기록
5. 구조화 출력 실패 시 현재와 같이 rule fallback으로 복귀한다.

### 5.2 로그 적재 방식 이관

로그는 목적별로 분리한다.

| 로그 | 저장 위치 | 목적 | 원문 포함 정책 |
|---|---|---|---|
| `ChatMessage` | 로컬 DB | 데모 UI 대화 이력 | 현재와 동일 |
| `AgentRunLog` | 로컬 DB | 실행 계획, 노드 로그, 화면 디버깅 | 현재와 동일하되 민감 필드 점검 |
| `AuditLog` | 로컬 DB | 이체 실행 감사 | 현재와 동일 |
| AWX `Logger` | AWX runtime log | 앱 상태/오류/운영 로그 | 원문 금지 |
| AWX `Tracer`/OTel | AWX collector | 요청, 노드, LLM, HITL trace | attribute는 식별자/상태/시간 중심 |
| AWX `LLMLog` | AWX LLM log | LLM 호출별 입력·출력·토큰·시간 | 기본 마스킹본 |
| AWX `Metering` | AWX usage/metering | 모델 사용량 집계 | 텍스트는 마스킹본 또는 요약 |

`src/agents/common/tracing.py`의 `traced(agent, node)`는 기존 상태 로그를 유지하면서 AWX span을 추가하는 방식으로 확장한다.

권장 span attribute:

```text
awx.session.id
banking.user.id
banking.session.id
langgraph.thread_id
agent.name
node.name
node.duration_ms
banking.intent
banking.pending_state
banking.response_type
gen_ai.system
gen_ai.request.model
```

민감정보 보호 원칙:

- 계좌번호는 뒤 4자리 외 마스킹한다.
- API key, credential value, token은 로그에 쓰지 않는다.
- 사용자 발화 원문은 AWX LLMLog에 바로 싣지 않고 `redact_user_text(...)`를 통과시킨다.
- 금액은 운영 정책에 따라 `amount_bucket` 또는 `has_amount=true`로 대체 가능하게 한다.

### 5.3 HITL trace 연속성

현재 `interrupt()`와 `Command(resume=...)`는 기능적으로 잘 동작하지만, HTTP 요청이 매번 새로 들어오므로 AWX/OTel trace는 끊길 수 있다. `langgraph-hitl-auto` 예제의 패턴을 적용한다.

1. 사용자 첫 요청에서 `banking.turn` span을 시작하고 trace carrier를 inject한다.
2. 그래프 결과가 `__interrupt__`이면 해당 carrier를 세션에 저장한다.
3. 다음 요청이 pending session resume이면 저장된 carrier를 parent context로 extract한다.
4. resume 완료 후 pending 상태가 해소되면 carrier를 삭제한다.

저장 위치 후보:

- 단기: `ChatSession.state_json`에 `trace_carrier`, `trace_id`, `pending_state` 저장.
- 안정화: `ChatSession`에 `trace_carrier_json`, `active_trace_id` 컬럼 추가.

### 5.4 실행 환경과 DB 경로

AWX 추론 환경은 소스 디렉토리 쓰기 권한이 제한될 수 있으므로 SQLite 경로를 명시적으로 런타임 쓰기 가능 영역에 둔다.

권장 기본값:

```text
DATABASE_URL=sqlite:///${PATH_TEMP:-/tmp}/banking_demo.db
CHECKPOINT_DB_PATH=${PATH_TEMP:-/tmp}/banking_checkpoints.db
```

다만 운영 수준의 이체 서비스라면 SQLite는 데모용으로만 유지하고, 외부 DB(PostgreSQL 등)를 AWX external resource/credential로 연결하는 것을 별도 운영화 과제로 둔다.

### 5.5 Flask 유지 여부

AWX 예제는 FastAPI가 많지만, 현 서비스는 Flask template UI와 blueprint가 이미 안정적으로 동작한다. 1차 이관에서는 Flask를 유지한다.

- `opentelemetry-instrument python app.py` 또는 `opentelemetry-instrument flask --app app run` 방식으로 자동 계측한다.
- AWX `fastapi.instrument_app(...)`는 Flask에는 직접 적용하지 않는다.
- 필요한 span은 `Tracer` 수동 계측으로 보강한다.
- FastAPI/ASGI 전환은 AWX 표준에서 강제될 때 별도 phase로 수행한다.

---

## 6. 단계별 수행 계획

### Phase 0. 기준선 동결 및 이관 범위 확정 (0.5일)

- 현재 기능 회귀 기준 수립: `pytest`, `scripts/smoke_test.py`, `scripts/web_smoke.py`.
- 현재 dirty worktree의 사용자 변경과 이관 변경 범위를 분리한다.
- AWX 환경에서 필요한 credential service id, provider alias, service type name, project id, flow id를 운영자에게 확인한다.
- 민감정보 로깅 정책을 확정한다.

완료 기준:

- 현재 테스트 결과와 주요 데모 시나리오 결과가 기록됨.
- AWX credential/resource 식별자 목록이 확정됨.

### Phase 1. AWX flow 실행 골격 구성 (1일)

- `awx/` 실행 메타 디렉토리와 `dist/awx-flow/` 생성 산출물 전략 확정.
- `awx/run-application.sh` 작성.
  - `PATH_SOURCE`, `PATH_TEMP`, `ROOT_PATH` 처리.
  - AWX SDK bootstrap helper 적용.
  - `opentelemetry-instrument`로 앱 실행.
- `awx/pyproject.toml` 작성.
  - 현재 `requirements.txt` 의존성 반영.
  - OTel 관련 의존성 추가: Flask/requests/httpx/logging/openai instrumentation 중 실제 사용분.
  - AWX SDK는 런타임 제공 전제로 직접 pin하지 않는다.
- `awx/awx-bootstrap.json` 작성.
- `scripts/build_awx_flow.py` 작성.
- `python scripts/build_awx_flow.py --clean`으로 `dist/awx-flow/` 생성.
- 생성 산출물에서 로컬 `awx run` 또는 동등 shell 실행으로 앱 기동 확인.

완료 기준:

- `dist/awx-flow/run-application.sh`로 현재 채팅 UI와 `/api/chat/message`가 정상 동작.
- `awx package` 전에 필요한 파일이 생성 산출물 아래에 모두 존재.

### Phase 2. AWX credential/resource 이관 (1일)

- `src/awx_runtime/credentials.py` 구현.
- `config.py`에 AWX credential 설정 추가.
  - `AWX_CREDENTIAL_SERVICE_ID`
  - `AWX_CREDENTIAL_PROVIDER_ALIAS=OpenAI`
  - `AWX_CREDENTIAL_SERVICE_TYPE_NAME=LLM`
  - `AWX_EXTERNAL_RESOURCE_SOLUTION_ID=BUILDER`
- `src/agents/context.py`의 `build_context(...)`에서 AWX credential resolver 사용.
- `src/agents/common/llm.py`의 `get_chat_model(...)`을 AWX credential 우선 경로로 변경.
- credential 조회 실패 시 기존 deterministic fallback 유지.
- credential 값 마스킹 테스트 추가.

완료 기준:

- 로컬 `.env` 키 없이도 deterministic 테스트 통과.
- AWX credential mock으로 `ChatOpenAI` 생성 경로 테스트 통과.
- credential secret이 로그/응답/debug_info에 노출되지 않음.

### Phase 3. AWX observability 및 LLMLog 적용 (1.5일)

- `src/awx_runtime/observability.py` 구현.
  - SDK import 성공 시 실제 `Logger`, `Tracer`, `LLMLog`, `Metering` 사용.
  - SDK import 실패 시 no-op fallback.
- `app.py` startup 로그를 `awx.core.Logger`로 보강.
- `run_banking_agent(...)`에 turn-level span 추가.
- `traced(...)` decorator에 node-level span 추가.
- LLM 호출 래퍼에서 `LLMLog.log(LogInput(...))` 호출.
- LLM response metadata에서 토큰 사용량 추출 가능 시 `input_tokens`, `output_tokens`, `token_usage` 기록.
- 필요 시 `Metering.collect(...)`를 LLM 호출 성공 후 비동기 또는 best-effort로 호출.
- AWX collector 장애가 비즈니스 응답 실패로 전파되지 않도록 예외 격리.

완료 기준:

- 각 사용자 요청에 대해 turn span, node span, LLM span/log가 생성됨.
- collector/LLMLog 전송 실패 시에도 이체 기능은 정상 응답.
- 로컬 `AgentRunLog` 기능은 유지.

### Phase 4. HITL trace continuity 적용 (1일)

- `src/awx_runtime/trace_context.py` 구현.
- `ChatSession.state_json` 또는 신규 컬럼에 trace carrier 저장.
- `run_banking_agent(...)`에서 pending interrupt 발생 시 carrier 저장.
- pending resume 요청에서 carrier를 parent context로 복원.
- 확인, 금액 되묻기, 동명이인 선택, OTP 시나리오 trace가 하나의 흐름으로 묶이는지 확인.

완료 기준:

- `awaiting_confirmation` 후 `확인` 요청이 같은 업무 trace로 연결됨.
- `awaiting_otp` 다회 오답 후 성공까지 trace 연결이 유지됨.
- pending 해소 후 다음 독립 요청은 새 trace로 시작.

### Phase 5. 패키징 및 AWX 구동 검증 (1일)

- `awx run`으로 앱 시작 검증.
- AWX 환경에서 `/chat`, `/api/chat/message`, `/agent-logs`, `/.well-known/agent-card.json` 확인.
- `awx package --message "ai-banking-transfer-agent awx migration"` 수행.
- artifact 생성 및 배포 요청 결과 확인.
- AWX Portal에서 credential, trace, LLMLog, metering 적재 확인.

완료 기준:

- AWX artifact 생성 성공.
- 배포된 앱에서 주요 데모 시나리오가 통과.
- AWX 로그/trace/LLMLog에 기대 필드가 적재됨.

### Phase 6. 운영 안정화 및 문서화 (1일)

- README에 AWX 실행 방법 추가.
- `.env.example`에 AWX 관련 local override만 추가하고 secret 직접 저장은 금지한다.
- `docs/AWX_운영_점검표.md` 작성.
- 장애 대응 절차 문서화.
  - credential 조회 실패
  - collector 미연결
  - checkpoint DB 쓰기 실패
  - AWX SDK import 실패
- 테스트/스모크 명령 정리.

완료 기준:

- 새 개발자가 문서만 보고 AWX run/package까지 재현 가능.
- 운영자가 credential/observability 문제를 구분할 수 있음.

총 예상 공수: 약 6 작업일. FastAPI 전환, 외부 DB 전환, Guardrail 정책 연동까지 포함하면 8~10 작업일로 재산정한다.

---

## 7. 테스트 계획

### 7.1 기존 회귀

- `pytest tests/ -v`
- `python scripts/smoke_test.py`
- `python scripts/web_smoke.py`

### 7.2 신규 단위 테스트

| 테스트 | 목적 |
|---|---|
| AWX SDK 미설치 no-op 테스트 | 로컬/CI에서 SDK 없이도 앱이 기동해야 함 |
| Credential resolver mock 테스트 | `Credential.get(...)` 결과에서 API key 추출 |
| Credential fallback 테스트 | AWX 실패 시 `.env` 또는 deterministic으로 복귀 |
| Redaction 테스트 | 계좌번호/API key/토큰/전화번호 마스킹 |
| LLMLog payload 테스트 | 필수 필드, 시간, status, custom metadata 구성 |
| Tracer decorator 테스트 | 기존 `node_logs` 유지 + span 예외 격리 |
| HITL carrier 테스트 | interrupt 저장, resume 복원, 완료 후 삭제 |

### 7.3 AWX 환경 스모크

1. `awx run` 후 `/chat` 접속.
2. "잔고 보여줘" 실행.
3. "엄마에게 5만원 보내줘" 후 "확인".
4. "집주인한테 350만원 보내줘" 후 "확인" → OTP → "123456".
5. "잔고 보여주고 자주 보내는 사람도 추천해줘" 병렬 fan-out 확인.
6. Portal에서 trace/LLMLog 적재 확인.

---

## 8. 리스크 및 대응

| 리스크 | 영향 | 대응 |
|---|---|---|
| AWX SDK import 불가 | 앱 기동 실패 가능 | 모든 SDK 연동은 no-op fallback 래퍼를 통해 호출 |
| Credential 조회 실패 | LLM 비활성화 | deterministic fallback 유지, UI에 provider 상태 표시 |
| Secret 로그 노출 | 보안 사고 | redaction 기본 적용, raw log opt-in 금지 또는 제한 |
| OTel collector 장애 | 응답 지연/실패 | observability 전송은 best-effort, 예외 삼킴 및 warning |
| HITL trace carrier 저장 오류 | trace 단절 | 기능은 유지하고 trace만 새로 시작, 오류 로그만 남김 |
| SQLite 쓰기 불가 | 체크포인트/채팅 실패 | `PATH_TEMP` 기본 경로 사용, 운영화 시 외부 DB 전환 |
| `flow/` 코드 중복 | 유지보수 비용 | 최종 구조 확정 후 루트와 flow 중 하나를 canonical source로 정리 |
| FastAPI 예제와 Flask 현행 차이 | 일부 SDK 자동화 미적용 | 1차는 수동 span/OTel로 대응, 필요 시 후속 ASGI 전환 |

---

## 9. 산출물

- AWX 배포 가능 `flow/` 소스
- AWX credential/resource bootstrap manifest
- AWX runtime wrapper 모듈
- LLM credential 이관 코드
- AWX observability/LLMLog/Metering 연동 코드
- HITL trace continuity 코드
- 회귀 테스트 및 AWX mock 테스트
- README 및 운영 점검 문서
- AWX package artifact 및 배포 검증 결과

---

## 10. 최종 인수 기준

1. `awx run`으로 앱이 정상 기동한다.
2. `awx package`로 artifact 생성이 성공한다.
3. 기존 주요 기능이 동일하게 동작한다.
   - 잔액 조회
   - 추천
   - 이체 확인
   - 동명이인 되묻기
   - 금액 되묻기
   - OTP
   - 확인 중 새 요청 handoff
4. LLM 호출은 AWX credential을 우선 사용한다.
5. AWX Portal 또는 collector에서 turn/node/LLM trace가 확인된다.
6. LLMLog에는 마스킹된 입출력, 모델, 시간, 상태, 토큰 정보가 적재된다.
7. SDK/collector/credential 장애가 금융 로직 실패로 전파되지 않는다.
8. secret 및 민감정보가 stdout, AWX Logger, OTel attribute, LLMLog에 평문 노출되지 않는다.
9. 기존 로컬 `AgentRunLog` 화면은 계속 동작한다.
10. 테스트와 스모크 시나리오가 통과한다.
