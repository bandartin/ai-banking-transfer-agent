# Agent 프로그램 표준 템플릿화 수행계획서

## 1. 목적

현재 `ai-banking-transfer-agent`는 단순 챗봇 예제가 아니라, Supervisor Agent, Sub-Agent, LangGraph workflow, A2A Agent Card, Tool Calling, Human-in-the-Loop, checkpoint, 감사 로그를 함께 갖춘 Multi-AI Agent 프로그램의 좋은 원형이다.

이 문서의 목적은 현재 프로그램에서 검증된 구조를 기준으로, 향후 다른 도메인의 Multi-AI Agent를 만들 때 반복해서 사용할 수 있는 표준 템플릿과 핵심 스킬셋을 정리하는 것이다.

최종 목표는 다음과 같다.

- 신규 Agent 프로그램을 만들 때 매번 구조를 새로 고민하지 않고 동일한 뼈대에서 시작한다.
- Supervisor, Sub-Agent, Tool, A2A, 상태 관리, 보안 정책, 테스트 방식을 일관되게 유지한다.
- 금융, 사내 업무, 검색/RAG, 운영 자동화, 고객 상담 등 여러 도메인으로 확장해도 유지보수 가능한 형태를 갖춘다.
- 개인 커리어 관점에서도 "멀티 에이전트 아키텍처를 설계하고 표준화할 수 있는 사람"이라는 포트폴리오 자산을 만든다.

## 2. 현재 프로그램의 핵심 구조

현재 프로그램은 다음 구조를 중심으로 동작한다.

```text
사용자 요청
  -> Supervisor Agent
     -> intent/slot/planning
     -> ExecutionPlan 생성
     -> LangGraph Send/Command로 Sub-Agent 호출
  -> Sub-Agent
     -> transfer / inquiry / recommend / security
     -> menu_search / product_guide / financial_calculator / tool_agent
  -> Tool Calling / Domain Service / External Adapter
  -> 결과 집계 및 응답 생성
  -> checkpoint, chat log, agent activity, audit 기록
```

현재 코드 기준의 주요 책임 분리는 다음과 같다.

| 영역 | 현재 위치 | 표준 템플릿에서의 의미 |
|---|---|---|
| Supervisor graph | `src/agents/supervisor/graph.py` | 전체 실행 계획, 라우팅, 결과 집계 |
| Planner | `src/agents/supervisor/planner.py` | LLM 또는 rule 기반 ExecutionPlan 생성 |
| Runtime context | `src/agents/context.py` | 사용자, 환경, LLM, 정책 값을 state와 분리 |
| Shared state | `src/agents/state.py` | graph 실행 중 변하는 값과 reducer 정의 |
| Contract schema | `src/agents/common/schemas.py` | 계획, slot, risk, transfer 등 구조화 계약 |
| Sub-Agent | `src/agents/subagents/*.py` | 도메인별 독립 업무 수행 단위 |
| A2A card | `src/agents/a2a/cards.py` | Agent discovery, capabilities, skills 명세 |
| Tool registry | `src/agents/tool_calling/registry.py` | 모델이 호출 가능한 tool 계약 |
| Tool policy | `src/agents/tool_calling/policy.py` | read/prepare/confirm/execute 권한 통제 |
| External tool adapter | `src/agents/tool_calling/external.py`, `awx_mcp.py` | AWX/MCP 등 외부 도구를 내부 Tool 계약으로 정규화 |
| Domain service | `src/agents/common/services/*.py` | DB/업무 규칙/계산/추천 등 결정론 로직 |
| Web/API boundary | `src/web/routes/*.py` | 사용자 인터페이스와 agent runtime의 연결부 |
| Tests | `tests/*.py` | planning, HITL, tool policy, AWX/MCP, integration readiness 검증 |

## 3. 표준 아키텍처 원칙

### 3.1 Supervisor는 "실행자"가 아니라 "계획자/조정자"로 둔다

Supervisor Agent는 모든 업무 로직을 직접 처리하지 않는다. Supervisor는 다음 역할에 집중한다.

- 사용자 요청의 의도와 필요한 작업 단위 판단
- 어떤 Sub-Agent를 어떤 순서 또는 병렬로 호출할지 결정
- `ExecutionPlan`을 구조화된 schema로 생성
- Sub-Agent 결과를 사용자 응답으로 통합
- 알 수 없는 요청, 충돌 요청, pending 상태를 상위 workflow로 정리

도메인 로직은 Sub-Agent와 Domain Service에 둔다. 이렇게 해야 신규 도메인을 추가할 때 Supervisor는 얇게 유지되고, 업무 확장은 Sub-Agent 단위로 일어난다.

### 3.2 State와 Runtime Context를 반드시 분리한다

표준 템플릿에서는 state와 context를 다음 기준으로 나눈다.

| 구분 | State | Runtime Context |
|---|---|---|
| 성격 | 실행 중 변하는 값 | 한 번의 invoke 동안 고정되는 값 |
| 예시 | intent, slots, pending data, agent results | user_id, session_id, LLM config, 정책 threshold |
| 저장 | checkpoint 대상 | 호출 시 주입 |
| 변경 주체 | graph node | runtime 구성부 |
| 목적 | workflow 진행 상태 | 환경/사용자/정책 주입 |

이 분리는 템플릿화에서 매우 중요하다. Agent 내부가 Flask, FastAPI, CLI, A2A server, batch job 중 어디에서 호출되는지 몰라도 같은 방식으로 실행될 수 있기 때문이다.

### 3.3 LLM은 판단 보조, 권한 행사는 코드가 담당한다

현재 프로그램의 가장 좋은 방향성은 LLM의 역할과 결정론적 코드의 역할을 분리한 점이다.

LLM 또는 LLM 기반 Tool Calling이 담당해도 되는 영역:

- 사용자 발화의 의도 분류
- 복합 요청을 여러 작업으로 나누는 planning
- read-only tool 선택
- 응답 문장 다듬기
- RAG/문서 검색 질의 생성

코드와 정책이 반드시 담당해야 하는 영역:

- 금액, 잔액, 한도, 계좌 검증
- 이체 실행
- OTP, 확인, 취소, 재시도
- side-effect tool 허용 여부
- 감사 로그 마스킹
- 외부 tool allowlist
- 개인정보/계좌번호/토큰 redaction

표준 템플릿에서는 이 원칙을 "LLM은 선택하고, 코드는 승인한다"로 고정하는 것을 권장한다.

### 3.4 Agent Card를 내부 planning과 외부 A2A의 공통 계약으로 사용한다

현재 `AGENT_CARDS`는 내부적으로 Supervisor prompt에 들어가고, 외부적으로 A2A discovery surface에도 사용된다. 이 방식은 유지하는 것이 좋다.

표준 Agent Card에는 다음 항목을 포함한다.

- `name`
- `description`
- `version`
- `skills`
- `input_modes`
- `output_modes`
- `read_only`
- `side_effect`
- `requires_confirmation`
- `requires_checkpoint`
- `collaborates_with`
- `examples`
- `owner`
- `failure_modes`

현재 카드에는 capability와 skills 중심의 설명이 잘 들어가 있다. 다음 단계에서는 `read_only`, `side_effect`, `requires_confirmation` 같은 안전 metadata를 추가하는 것을 권장한다.

### 3.5 Tool Calling은 Agent 구조를 대체하지 않고 보완한다

Tool Calling은 "모델이 함수 호출을 선택하는 실행 방식"이지, 전체 Agent 아키텍처의 대체물이 아니다.

권장 위치:

- read-only 조회
- deterministic 계산
- RAG 검색
- 외부 MCP read tool
- 이체 준비 단계처럼 실행 전 요약 생성

제한할 위치:

- 실제 이체 실행
- 승인/확정 처리
- 권한 변경
- 데이터 삭제
- 고객에게 되돌릴 수 없는 영향이 있는 action

현재 코드처럼 `side_effect`를 `read`, `prepare`, `confirm`, `execute`로 분류하고, 모델에게는 `read` 또는 제한된 `prepare`까지만 노출하는 구조가 표준 템플릿에 적합하다.

## 4. 표준 템플릿 디렉터리 제안

향후 새 프로젝트를 만들 때 다음 구조를 기본 골격으로 삼는 것을 제안한다.

```text
agent-template/
  README.md
  requirements.txt
  .env.example
  app.py 또는 main.py

  src/
    agents/
      context.py
      state.py

      supervisor/
        graph.py
        planner.py
        prompts.py

      subagents/
        __init__.py
        example_domain_agent.py
        tool_agent.py

      a2a/
        __init__.py
        cards.py
        protocol.py

      tool_calling/
        __init__.py
        registry.py
        runner.py
        policy.py
        external.py
        mcp_adapter.py

      common/
        schemas.py
        parsing.py
        llm.py
        tracing.py
        services/
          __init__.py
          domain_service.py
          security_rules.py

    integrations/
      ports.py
      factory.py
      mock_adapter.py
      errors.py

    web/
      routes/

    models/

  tests/
    test_planner.py
    test_agent_flow.py
    test_tool_policy.py
    test_a2a.py
    test_integration_readiness.py

  docs/
    architecture.md
    agent_cards.md
    tool_policy.md
    operations.md
    test_scenarios.md
```

핵심은 "업무 도메인만 갈아 끼울 수 있는 고정 골격"을 만드는 것이다. 금융 이체, 지식 검색, 사내 결재, 장애 대응, 문서 자동화가 모두 같은 구조에서 출발할 수 있어야 한다.

## 5. 표준 Agent 추가 절차

신규 Sub-Agent를 추가할 때는 다음 순서를 표준으로 삼는다.

1. Agent Card 작성
   - 이름, 설명, skill, 예시, side-effect, confirmation 필요 여부 정의

2. Contract schema 작성
   - 입력 slot, 출력 result, error, audit data를 Pydantic schema로 정의

3. Domain Service 작성
   - DB 조회, 외부 API 호출, 계산, 검증 등 결정론 로직을 agent node 밖으로 분리

4. Subgraph 작성
   - 단순 read-only agent는 `START -> run -> END`
   - 다단계 workflow는 `extract -> validate -> confirm -> execute -> compose`처럼 node 분리

5. Supervisor planner 연결
   - intent mapping 또는 LLM planner prompt에 Agent Card 반영
   - 병렬 가능 여부와 side-effect 충돌 여부 확인

6. Tool Calling 연결 여부 판단
   - read-only 또는 prepare tool이면 registry에 추가
   - execute/confirm 성격이면 모델 호출 대상에서 제외

7. A2A 노출 여부 결정
   - 외부 호출 가능한 agent인지 판단
   - multi-turn이 필요한 경우 task id, resume, pending action 조회 API를 함께 설계

8. 테스트 추가
   - planner route test
   - subgraph 단위 test
   - HITL resume test
   - tool policy test
   - audit/redaction test

## 6. 핵심 스킬셋 정리

### 6.1 Supervisor Agent 설계

필수 역량:

- 복합 요청을 `ExecutionPlan`으로 구조화
- 병렬 실행 가능한 작업과 순차 실행해야 하는 작업 구분
- side-effect가 있는 작업을 단일 workflow로 제한
- Sub-Agent 결과를 사용자 응답으로 집계
- pending 상태에서 새 요청이 들어왔을 때 상위 graph로 되돌리는 설계

현재 프로그램의 강점:

- `ExecutionPlan`과 `PlanStep`으로 planning 결과가 명확하다.
- `Send`를 통해 read-only agent를 병렬 실행할 수 있다.
- transfer처럼 side-effect가 있는 업무는 독립 workflow로 제한한다.

개선 제안:

- Agent Card의 metadata를 planner policy에 더 직접적으로 반영한다.
- planner 테스트용 gold set을 별도 파일로 관리한다.
- LLM planner 결과를 검사하는 policy validator를 추가한다.

### 6.2 LangGraph 설계

필수 역량:

- `StateGraph` 기반 node/edge 구성
- `context_schema`를 통한 runtime 주입
- `Send` 기반 fan-out
- `Command(goto=...)` 기반 동적 라우팅
- `Command(graph=Command.PARENT)` 기반 부모 graph handoff
- `interrupt()`와 `Command(resume=...)` 기반 HITL
- checkpointer 기반 durable execution
- reducer를 통한 병렬 branch 결과 병합

현재 프로그램의 강점:

- 최신 LangGraph 기능을 실제 업무 흐름에 폭넓게 적용했다.
- 확인, 금액 보완, 모호성 해소, OTP를 interrupt 기반으로 처리한다.
- checkpoint를 사용해 multi-turn 상태를 유지한다.

개선 제안:

- 각 subgraph의 입출력 contract를 문서와 테스트로 더 명확히 고정한다.
- graph trace를 운영 관점에서 보기 쉬운 event schema로 정리한다.
- 장기적으로 SQLite checkpointer와 운영 DB의 역할 분리를 문서화한다.

### 6.3 A2A 설계

필수 역량:

- Agent Card 기반 discovery
- 내부 Agent Card와 외부 A2A metadata의 일관성 유지
- JSON-RPC 또는 HTTP endpoint로 agent invoke surface 제공
- 외부 호출 시 인증, 권한, session, task id 설계

현재 프로그램의 강점:

- Agent Card를 내부 prompt와 외부 endpoint 양쪽에 활용한다.
- Supervisor 경유 호출과 Sub-Agent capability 명세가 분리되어 있다.

개선 제안:

- 외부 A2A에서 side-effect agent를 직접 호출하지 않는 정책을 문서화한다.
- transfer 같은 multi-turn agent를 외부에 열려면 task id, pending action, resume API가 필요하다.
- Agent Card에 보안/권한 metadata를 추가한다.

### 6.4 Tool Calling 설계

필수 역량:

- 모델이 호출 가능한 tool schema 정의
- handler와 runtime context 분리
- side-effect policy gate
- allowlist 기반 외부 tool 노출
- audit event와 redaction
- LLM unavailable 시 deterministic fallback

현재 프로그램의 강점:

- `AgentTool` 계약이 명확하다.
- `side_effect` 정책이 있고 execute 성격 tool을 차단한다.
- AWX MCP tool도 allowlist를 거쳐 내부 Tool 계약으로 감싼다.
- tool audit event가 마스킹되어 남는다.

개선 제안:

- `read`, `prepare`, `confirm`, `execute`에 대한 표준 정의를 문서화한다.
- 모든 external tool에는 owner, data classification, timeout, retry, failure behavior를 붙인다.
- prepare tool이 confirmation workflow로 넘어가는 handoff contract를 더 엄격히 검증한다.

### 6.5 Observability와 운영 설계

필수 역량:

- agent activity log
- node trace
- tool audit event
- checkpoint snapshot
- LangSmith 또는 OpenTelemetry trace
- 민감정보 redaction
- readiness check

현재 프로그램의 강점:

- `AgentRunLog`, `agent_activity`, `node_logs`, `graph_trace`가 있다.
- AWX readiness check와 masked trace sample 방향이 이미 잡혀 있다.

개선 제안:

- 운영자가 보는 trace event schema를 표준화한다.
- 실패 원인을 `planner_failed`, `tool_policy_blocked`, `external_timeout`, `validation_failed`처럼 코드화한다.
- dashboard에서 plan, agent timeline, tool audit, final response를 한 화면에 비교할 수 있게 한다.

## 7. 표준 템플릿화 수행 계획

### Phase 1. 현재 구조 기준 문서화

목표:

- 현재 프로그램의 agent 구조를 재사용 가능한 reference architecture로 정리한다.

작업:

- Supervisor/Sub-Agent 흐름 다이어그램 작성
- State vs Context 기준 문서화
- Agent Card 표준 필드 정의
- Tool side-effect 정책 문서화
- HITL 패턴 문서화
- 테스트 시나리오 목록화

산출물:

- `docs/architecture.md`
- `docs/agent_cards.md`
- `docs/tool_policy.md`
- `docs/hitl_patterns.md`
- `docs/test_scenarios.md`

### Phase 2. Agent Template 골격 분리

목표:

- 현재 banking domain에 묶인 부분과 재사용 가능한 framework 부분을 구분한다.

작업:

- `BankingContext`에서 공통 context와 banking-specific context 구분
- `BankingState`에서 공통 state key와 도메인 state key 구분
- `AgentTool`, `ToolPolicy`, `A2A Card`, `Tracing`을 공통 패키지 후보로 정리
- 신규 프로젝트 scaffold 예시 작성

산출물:

- `docs/template_structure.md`
- `docs/template_scaffold_checklist.md`
- `examples/minimal_agent_template/`

### Phase 3. 표준 계약 강화

목표:

- Agent가 많아져도 충돌하지 않도록 계약 중심으로 관리한다.

작업:

- Agent Card schema 도입
- `side_effect`, `requires_confirmation`, `read_only`, `parallel_safe` 필드 추가
- planner 결과 validation layer 추가
- external tool metadata schema 정의
- tool audit event schema 고정

산출물:

- `src/agents/a2a/card_schema.py`
- `src/agents/tool_calling/contracts.py`
- `docs/contracts.md`

### Phase 4. 테스트 템플릿화

목표:

- 신규 Agent 추가 시 반드시 통과해야 하는 공통 테스트 패턴을 만든다.

작업:

- planner routing gold set 작성
- Sub-Agent 단위 테스트 fixture 작성
- HITL resume 공통 테스트 helper 작성
- Tool policy 공통 테스트 helper 작성
- A2A endpoint contract test 작성

산출물:

- `tests/fixtures/planner_goldens.json`
- `tests/helpers/agent_flow.py`
- `tests/test_agent_contracts.py`

### Phase 5. 운영/배포 템플릿화

목표:

- 로컬 데모를 넘어 운영 환경에서도 같은 구조로 배포할 수 있게 한다.

작업:

- `.env.example` 표준화
- readiness check 표준화
- AWX bootstrap checklist 정리
- LangSmith/OTel trace 설정 문서화
- 민감정보 masking 기준 문서화

산출물:

- `docs/operations.md`
- `docs/readiness_check.md`
- `scripts/check_agent_template_readiness.py`

## 8. 방향성 검토

현재 방향성은 전반적으로 맞다. 특히 다음 판단은 매우 좋다.

- Supervisor/Sub-Agent 계층을 둔 점
- LangGraph를 단순 chain이 아니라 durable workflow 엔진으로 사용한 점
- A2A Agent Card를 내부 planning과 외부 discovery 양쪽에 활용한 점
- Tool Calling을 read-only/prepare 중심으로 제한한 점
- 이체 실행 같은 고위험 action을 결정론 코드와 HITL로 통제한 점
- 테스트와 readiness check를 구조의 일부로 둔 점

다만 다음 부분은 앞으로 더 명확히 해야 한다.

1. "Agent"와 "Tool"의 경계를 더 엄격히 정의해야 한다.
   - Agent는 목표와 workflow를 가진 업무 수행자다.
   - Tool은 Agent가 호출하는 단일 기능이다.
   - Tool Calling Agent가 모든 Sub-Agent를 대체하게 만들면 구조가 흐려진다.

2. A2A는 내부 handoff와 외부 protocol을 구분해야 한다.
   - 내부 A2A는 LangGraph `Send`/`Command`로 충분하다.
   - 외부 A2A는 인증, 권한, task lifecycle, resume protocol이 필요하다.

3. side-effect 정책은 architecture 문서의 중심 원칙이 되어야 한다.
   - `read`: 조회, 검색, 계산
   - `prepare`: 실행 전 요약/검증/초안 생성
   - `confirm`: 사용자 승인 대기
   - `execute`: 실제 변경/송금/삭제/등록
   - 모델 직접 호출 허용 범위는 기본적으로 `read`, 제한적으로 `prepare`까지다.

4. Planner validation을 별도 계층으로 두는 것이 좋다.
   - LLM이 `transfer + recommend`를 동시에 계획하면 거부하거나 재계획해야 한다.
   - `parallel_safe=false`인 Agent는 fan-out 대상에서 제외해야 한다.
   - `requires_confirmation=true`인 작업은 반드시 HITL path를 타야 한다.

5. 포트폴리오 관점에서는 "패턴 이름"을 붙여 관리하는 것이 좋다.
   - Supervisor Planning Pattern
   - Agent Card Discovery Pattern
   - Read/Prepare/Execute Tool Policy Pattern
   - LangGraph HITL Checkpoint Pattern
   - A2A Internal/External Boundary Pattern
   - Deterministic Domain Service Pattern

## 9. 우선순위 제안

가장 먼저 할 일은 코드를 크게 바꾸는 것이 아니라 표준을 고정하는 것이다.

권장 우선순위:

1. Agent Card metadata 확장
2. Tool side-effect 정책 문서화 및 schema화
3. Planner validation layer 추가
4. 신규 Agent 추가 checklist 작성
5. minimal template scaffold 생성
6. planner gold test 도입
7. 운영 trace/audit event schema 정리

이 순서가 좋은 이유는, 현재 프로그램은 이미 기능적으로 풍부하므로 당장 추상화부터 하면 오히려 복잡해질 수 있기 때문이다. 먼저 계약과 정책을 고정하고, 그 다음 공통 골격을 분리하는 편이 안전하다.

## 10. 신규 프로젝트 시작용 체크리스트

새 Multi-AI Agent 프로젝트를 만들 때 다음 질문에 답하면 표준 템플릿을 일관되게 적용할 수 있다.

- 이 프로젝트의 Supervisor는 어떤 결정을 하는가?
- Sub-Agent는 몇 개이며 각각의 책임은 무엇인가?
- 어떤 Agent가 read-only이고 어떤 Agent가 side-effect를 가지는가?
- 병렬 실행 가능한 작업은 무엇인가?
- 반드시 사용자 확인이 필요한 작업은 무엇인가?
- checkpoint가 필요한 multi-turn 지점은 어디인가?
- LLM이 선택해도 되는 tool은 어디까지인가?
- 외부 MCP/AWX/API tool은 allowlist로 제한되는가?
- 감사 로그에 남겨야 할 event는 무엇인가?
- 마스킹해야 할 데이터는 무엇인가?
- 테스트 gold set은 어떤 대표 발화로 구성되는가?

## 11. 결론

현재 프로그램은 Multi-AI Agent 표준 템플릿의 출발점으로 충분히 좋은 구조를 가지고 있다. 특히 Supervisor 중심 orchestration, LangGraph workflow, A2A discovery, Tool Calling policy, HITL checkpoint가 함께 들어가 있어 단순 예제보다 훨씬 실무형이다.

앞으로의 핵심은 기능을 더 많이 붙이는 것이 아니라, 이 구조를 "반복 가능한 표준"으로 굳히는 것이다. Agent Card, Tool Policy, Planner Validation, Test Gold Set, Operations Checklist를 고정하면, 이후 어떤 도메인의 Agent를 만들더라도 균일한 구조와 설명력을 유지할 수 있다.

