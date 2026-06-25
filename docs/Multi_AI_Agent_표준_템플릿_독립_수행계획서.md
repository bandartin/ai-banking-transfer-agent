# Multi-AI Agent 표준 템플릿 독립 수행계획서

## 1. 문서 목적

이 문서는 특정 프로젝트, 특정 코드베이스, 특정 업무 시스템에 종속되지 않는 Multi-AI Agent 프로그램 표준 수행계획서이다.

목표는 앞으로 다양한 Agent 시스템을 만들 때 공통으로 적용할 수 있는 설계 원칙, 아키텍처 구조, 개발 순서, 검증 기준, 운영 기준을 하나의 기준 문서로 정리하는 것이다.

이 문서를 기준으로 개발할 Agent 시스템은 다음 특성을 가져야 한다.

- 단일 챗봇이 아니라 여러 전문 Agent가 협업하는 구조
- Supervisor Agent가 전체 의도 파악, 계획, 라우팅, 응답 집계를 담당하는 구조
- Sub-Agent를 서비스 목적과 업무 성격에 따라 자유롭게 설계할 수 있는 구조
- Sub-Agent 간 협업과 통신이 가능한 구조
- Tool Calling은 안전한 범위에서 통제된 방식으로 사용하는 구조
- A2A, MCP, API, RAG 등 외부 연동이 가능한 확장 구조
- Human-in-the-Loop, checkpoint, 감사 로그를 포함한 운영 가능한 구조
- 신규 Agent를 추가해도 전체 구조가 흔들리지 않는 표준화된 구조

## 2. 목표 아키텍처 개요

표준 Multi-AI Agent 프로그램은 다음 계층으로 구성한다.

```text
사용자 또는 외부 시스템
  -> Interface Layer
     - Web UI
     - API
     - A2A endpoint
     - Batch/CLI

  -> Supervisor Agent
     - 의도 분류
     - 작업 계획 수립
     - Agent 선택
     - 병렬/순차 실행 판단
     - 결과 집계
     - 최종 응답 생성

  -> Agent Runtime / Workflow Engine
     - graph 실행
     - state 관리
     - context 주입
     - checkpoint
     - interrupt/resume
     - trace

  -> Sub-Agent Layer
     - 서비스별로 직접 정의하는 전문 Agent 조직
     - 예: 데이터분석 Agent, 마케팅 Agent, 회계 Agent, 심사 Agent, 리서치 Agent
     - Agent 간 협업, 위임, 검토, 결과 공유

  -> Tool / Service Layer
     - 내부 업무 서비스
     - DB 조회
     - 외부 API
     - MCP tool
     - RAG retriever
     - deterministic calculator

  -> Governance / Operations Layer
     - 권한 정책
     - side-effect 통제
     - 감사 로그
     - 민감정보 마스킹
     - 모니터링
     - 테스트/검증
```

Sub-Agent Layer의 구성은 고정 목록이 아니다. 실제 서비스가 어떤 목적을 갖는지, 어떤 업무 단위가 존재하는지, 어떤 전문성이 분리되어야 하는지에 따라 매번 새로 설계한다. 회사에서 데이터분석팀, 마케팅팀, 회계팀, 법무팀, 운영팀을 나누듯이 Agent도 업무 책임과 협업 방식에 따라 나눈다.

핵심 철학은 다음 한 문장으로 정리할 수 있다.

> Supervisor는 계획하고, Sub-Agent는 수행하며, Tool은 기능을 제공하고, 정책 계층은 실행 권한을 통제한다.

## 3. 핵심 설계 원칙

### 3.1 Agent와 Tool을 구분한다

Agent와 Tool은 역할이 다르다.

| 구분 | Agent | Tool |
|---|---|---|
| 성격 | 목표를 가진 업무 수행자 | 특정 기능을 수행하는 함수/도구 |
| 책임 | 판단, 절차, 상태 전이, 협업 | 조회, 계산, 검색, API 호출 |
| 예시 | 결재 Agent, 검색 Agent, 분석 Agent | 문서 검색, 금액 계산, 고객 조회 |
| 상태 | workflow state를 가질 수 있음 | 되도록 stateless |
| 제어 | Supervisor 또는 다른 Agent가 호출 | Agent 또는 모델이 호출 |

표준 원칙:

- 업무 흐름이 있으면 Agent로 만든다.
- 단일 기능이면 Tool로 만든다.
- Tool Calling Agent가 전체 구조를 대체하지 않도록 한다.

### 3.2 Supervisor Agent는 얇게 유지한다

Supervisor Agent는 모든 업무 로직을 직접 처리하지 않는다.

Supervisor의 책임:

- 사용자 요청 이해
- 작업 계획 생성
- Sub-Agent 선택
- 병렬 실행 가능 여부 판단
- 실행 결과 집계
- 응답 방향 결정
- 실패나 불확실성에 대한 상위 제어

Supervisor가 하지 말아야 할 일:

- DB 업무 규칙 직접 처리
- 외부 API 세부 로직 직접 구현
- 금액, 권한, 승인 같은 고위험 판단을 LLM에게 위임
- 특정 도메인 로직을 과도하게 포함

Supervisor는 오케스트레이터이고, 도메인 업무는 Sub-Agent와 Service가 담당해야 한다.

### 3.3 State와 Context를 분리한다

Multi-turn Agent에서는 상태 관리가 구조의 중심이다.

| 구분 | State | Context |
|---|---|---|
| 의미 | 실행 중 바뀌는 값 | 한 번의 실행 동안 고정되는 값 |
| 예시 | intent, slots, plan, pending action, result | user_id, tenant_id, policy, model config |
| 저장 | checkpoint 대상 | 호출 시 주입 |
| 변경 | Agent node가 변경 | runtime이 구성 |
| 목적 | workflow 진행 | 실행 환경 제공 |

표준 원칙:

- 사용자의 요청 처리 중 변하는 값은 State에 둔다.
- 사용자 프로필, 권한, 모델 설정, 정책 값은 Context에 둔다.
- Agent 내부에서 Web framework나 global config에 직접 의존하지 않는다.

### 3.4 LLM의 역할과 코드의 역할을 분리한다

LLM은 유연한 판단과 언어 처리를 잘하지만, 모든 권한을 가져서는 안 된다.

LLM이 담당해도 되는 영역:

- 의도 분류
- 계획 초안 생성
- 검색 질의 생성
- read-only tool 선택
- 응답 문장 구성
- 사용자 입력의 자연어 해석

코드와 정책이 담당해야 하는 영역:

- 권한 검증
- 금액/수량/한도 계산
- 최종 실행
- 승인/취소
- 민감정보 처리
- 외부 tool 노출 여부
- 감사 로그 생성
- side-effect 차단

표준 원칙:

> LLM은 제안하고, 코드는 검증하며, 정책은 실행 권한을 결정한다.

### 3.5 Side Effect를 등급화한다

Tool과 Agent는 side-effect 수준에 따라 분류해야 한다.

| 등급 | 의미 | 모델 직접 호출 |
|---|---|---|
| `read` | 조회, 검색, 계산 | 허용 가능 |
| `prepare` | 실행 전 요약, 초안, 사전 검증 | 제한적 허용 |
| `confirm` | 사용자 승인 대기 | 모델 단독 불가 |
| `execute` | 실제 변경, 송금, 삭제, 등록 | 모델 직접 호출 금지 |

표준 원칙:

- 기본적으로 모델은 `read` tool만 호출한다.
- `prepare`는 명확한 정책 gate가 있을 때만 허용한다.
- `confirm`과 `execute`는 반드시 코드 workflow와 사용자 확인을 거친다.
- 외부 MCP/API tool도 반드시 side-effect allowlist를 통해 노출한다.

### 3.6 Sub-Agent 조직은 서비스마다 다시 설계한다

Sub-Agent는 미리 정해진 종류를 채워 넣는 방식으로 만들지 않는다. 서비스의 목적, 업무 절차, 책임 경계, 필요한 전문성에 따라 사용자가 직접 깊이 관여하여 설계해야 한다.

좋은 Sub-Agent 분리는 회사의 부서 설계와 비슷하다.

| 조직 비유 | Agent 설계 의미 |
|---|---|
| 데이터분석팀 | 데이터 수집, 지표 계산, 인사이트 도출을 맡는 Agent |
| 마케팅팀 | 캠페인 기획, 고객 세그먼트, 메시지 전략을 맡는 Agent |
| 회계팀 | 비용, 정산, 재무 규칙 검토를 맡는 Agent |
| 법무팀 | 규정, 계약, 리스크 검토를 맡는 Agent |
| 운영팀 | 실행 상태 확인, 장애 대응, 후속 조치를 맡는 Agent |

표준 원칙:

- Sub-Agent 목록은 템플릿이 강제하지 않는다.
- 각 서비스의 실제 업무 분장에 맞춰 Agent 조직도를 먼저 그린다.
- Agent는 역할 이름보다 책임 경계가 더 중요하다.
- 업무가 서로 다른 판단 기준, 데이터, 승인 절차를 갖는다면 별도 Agent로 나눌 수 있다.
- 단순 기능 차이는 Agent가 아니라 Tool 또는 Service로 분리한다.
- 사용자가 직접 정의한 Agent 조직이 표준 구조 위에 올라가는 방식이 가장 바람직하다.

### 3.7 Agent 간 협업 구조를 설계한다

Multi-AI Agent의 장점은 Supervisor가 여러 Agent를 호출하는 데서 끝나지 않는다. Sub-Agent가 다른 Sub-Agent에게 검토, 보완, 위험 평가, 추가 분석을 요청하는 협업 구조를 가질 수 있어야 한다.

Agent 간 협업 유형:

| 협업 유형 | 설명 | 예시 |
|---|---|---|
| 위임 | 한 Agent가 특정 하위 작업을 다른 Agent에게 맡김 | 마케팅 Agent가 데이터분석 Agent에게 고객 세그먼트 요청 |
| 검토 | 실행 전 다른 Agent가 결과를 검증 | 회계 Agent가 비용 집행안을 검토 |
| 보완 | 한 Agent의 결과를 다른 Agent가 풍부하게 만듦 | 리서치 Agent 결과를 요약 Agent가 임원 보고 형태로 정리 |
| 합의 | 여러 Agent 결과를 비교해 최종 판단 | 법무 Agent와 보안 Agent가 정책 위반 여부 공동 판단 |
| 에스컬레이션 | 위험하거나 불확실한 작업을 상위 Agent나 사람에게 넘김 | 실행 Agent가 승인 Agent 또는 사용자 확인으로 넘김 |

표준 원칙:

- Agent 간 직접 통신은 명시적인 contract를 통해 이루어져야 한다.
- 협업 요청과 응답은 schema로 정의한다.
- side-effect가 있는 협업은 반드시 Supervisor 또는 Policy Layer가 통제한다.
- read-only 분석 협업은 병렬 또는 직접 handoff가 가능하다.
- 고위험 실행 협업은 HITL과 audit log를 포함해야 한다.

## 4. 표준 구성 요소

### 4.1 Supervisor Agent

Supervisor Agent는 Multi-AI Agent 구조의 중심이다.

필수 기능:

- 사용자 요청 분석
- `ExecutionPlan` 생성
- Agent 선택
- 병렬 실행 가능한 작업 분리
- 순차 실행이 필요한 작업 관리
- Sub-Agent 결과 집계
- 최종 응답 생성

표준 출력 예시:

아래 Agent 이름은 예시다. 실제로는 사용자가 설계한 서비스별 Agent 조직도의 이름이 들어간다.

```json
{
  "primary_intent": "document_search",
  "parallel": true,
  "steps": [
    {
      "agent": "PolicyResearchAgent",
      "task": "retrieve_policy_documents",
      "reason": "사용자가 규정 근거를 요청함"
    },
    {
      "agent": "ReportWritingAgent",
      "task": "summarize_related_cases",
      "reason": "관련 사례 요약이 필요함"
    }
  ]
}
```

### 4.2 Sub-Agent

Sub-Agent는 특정 업무 책임을 가진 독립 실행 단위다. 단, 어떤 Sub-Agent가 필요한지는 서비스마다 다르다. 표준 템플릿은 `SearchAgent`, `AnalysisAgent` 같은 고정 목록을 요구하지 않는다. 대신 서비스를 설계하는 사람이 실제 업무 목적과 책임 경계를 기준으로 Agent 조직을 직접 정의한다.

Sub-Agent 설계는 다음 질문에서 시작한다.

- 이 서비스는 어떤 핵심 업무를 수행하는가?
- 실제 조직이라면 어떤 부서나 담당자로 나눌 수 있는가?
- 어떤 업무는 독립 판단이 필요한가?
- 어떤 업무는 다른 업무의 검토나 승인이 필요한가?
- 어떤 업무는 병렬로 수행해도 되는가?
- 어떤 업무는 반드시 순차적으로 수행되어야 하는가?
- 어떤 업무는 실행 권한이 있고, 어떤 업무는 조회/분석만 하는가?

예시 Agent 유형은 다음처럼 서비스별로 달라질 수 있다.

| 서비스 유형 | 가능한 Sub-Agent 예시 |
|---|---|
| 데이터 분석 서비스 | 데이터수집 Agent, 지표분석 Agent, 이상탐지 Agent, 리포트작성 Agent |
| 마케팅 자동화 서비스 | 고객세그먼트 Agent, 캠페인기획 Agent, 콘텐츠작성 Agent, 성과분석 Agent |
| 회계/정산 서비스 | 비용검토 Agent, 증빙확인 Agent, 정산 Agent, 승인요청 Agent |
| 법무/계약 서비스 | 조항검토 Agent, 리스크분석 Agent, 판례검색 Agent, 계약요약 Agent |
| IT 운영 서비스 | 모니터링 Agent, 장애분석 Agent, 조치추천 Agent, 실행 Agent |
| 지식 검색 서비스 | 문서검색 Agent, 근거검증 Agent, 요약 Agent, 답변작성 Agent |

위 목록은 예시일 뿐이다. 실제 프로젝트에서는 사용자가 서비스 목적에 맞춰 Agent 조직도를 직접 설계하는 것을 전제로 한다.

Sub-Agent 설계 기준:

- 하나의 Agent는 하나의 명확한 책임을 가진다.
- 입력과 출력 schema를 명확히 둔다.
- side-effect 여부를 명시한다.
- 실패 시 반환할 error contract를 정의한다.
- 독립 테스트가 가능해야 한다.
- 다른 Agent와 협업해야 하는 경우 요청/응답 contract를 정의한다.
- 어떤 Agent가 어떤 Agent에게 위임, 검토, 보완, 에스컬레이션할 수 있는지 명시한다.

### 4.3 Agent Collaboration Contract

Agent 간 협업을 허용하려면 통신 규약이 필요하다. 협업은 자유로운 자연어 대화만으로 처리하지 않고, 가능한 한 구조화된 요청과 응답으로 관리한다.

표준 협업 요청 예시:

```json
{
  "request_id": "collab-2026-001",
  "from_agent": "MarketingAgent",
  "to_agent": "DataAnalysisAgent",
  "collaboration_type": "analysis_request",
  "task": "최근 3개월 고객 구매 데이터를 기준으로 캠페인 대상 세그먼트를 추천한다",
  "input": {
    "period": "last_3_months",
    "target_metric": "purchase_frequency"
  },
  "constraints": {
    "side_effect_allowed": false,
    "deadline_ms": 10000
  }
}
```

표준 협업 응답 예시:

```json
{
  "request_id": "collab-2026-001",
  "from_agent": "DataAnalysisAgent",
  "to_agent": "MarketingAgent",
  "status": "completed",
  "result": {
    "segments": [
      {
        "name": "고빈도 재구매 고객",
        "reason": "최근 3개월 구매 빈도가 높고 이탈 가능성이 낮음"
      }
    ]
  },
  "confidence": 0.86,
  "requires_review": false
}
```

Agent 간 협업 설계 기준:

- 협업 요청에는 요청자, 수신자, 작업 목적, 입력값, 제한 조건이 있어야 한다.
- 협업 응답에는 상태, 결과, 신뢰도, 후속 검토 필요 여부가 있어야 한다.
- 협업 결과는 Supervisor가 집계하거나 요청 Agent가 자신의 workflow에 반영한다.
- Agent 간 협업도 trace와 audit 대상이 되어야 한다.
- 직접 협업이 복잡해지면 Supervisor를 통해 orchestration하는 방식으로 되돌린다.

### 4.4 Agent Card

Agent Card는 Agent의 능력 명세서다. 내부 Supervisor planning과 외부 A2A discovery에 모두 사용할 수 있다.

표준 Agent Card 필드:

아래는 예시일 뿐이며, 실제 Agent 이름과 skill은 서비스별 Agent 조직도에 맞춰 바꾼다.

```json
{
  "name": "PolicyResearchAgent",
  "description": "정책 자료를 조사하고 근거를 정리하는 Agent",
  "version": "1.0.0",
  "skills": [
    {
      "id": "policy_search",
      "name": "정책 검색",
      "description": "정책 문서를 검색하고 근거를 반환한다",
      "examples": ["휴가 규정 찾아줘", "보안 예외 승인 기준 알려줘"]
    }
  ],
  "read_only": true,
  "side_effect": "read",
  "parallel_safe": true,
  "requires_confirmation": false,
  "requires_checkpoint": false,
  "input_modes": ["text/plain", "application/json"],
  "output_modes": ["application/json"],
  "collaborates_with": ["ReportWritingAgent", "RiskReviewAgent"],
  "owner": "AI Platform Team"
}
```

Agent Card는 단순 설명서가 아니라 planning policy의 입력이 되어야 한다.

### 4.5 Tool Registry

Tool Registry는 모델 또는 Agent가 호출할 수 있는 tool 목록을 관리한다.

표준 Tool 정의:

```json
{
  "name": "search_policy_documents",
  "description": "정책 문서를 검색한다",
  "parameters": {
    "type": "object",
    "properties": {
      "query": {
        "type": "string",
        "description": "검색 질의"
      }
    },
    "required": ["query"]
  },
  "side_effect": "read",
  "owner": "Knowledge Team",
  "timeout_ms": 5000,
  "data_classification": "internal"
}
```

Tool Registry의 표준 정책:

- 모든 tool은 이름, 설명, parameter schema를 가져야 한다.
- 모든 tool은 side-effect 등급을 가져야 한다.
- 외부 tool은 allowlist를 통과해야 한다.
- 민감한 인자와 결과는 audit log 저장 전 마스킹한다.
- execute 성격 tool은 모델에게 직접 노출하지 않는다.

### 4.6 Workflow Engine

Multi-Agent 구조에는 workflow engine이 필요하다.

필수 기능:

- graph 기반 node 실행
- 조건부 라우팅
- 병렬 fan-out
- parent/child handoff
- interrupt/resume
- checkpoint
- trace
- state reducer

Workflow가 필요한 이유:

- 대화는 한 번에 끝나지 않는다.
- 사용자 확인, 추가 정보, 승인, 재시도가 필요하다.
- 실행 중단 후 재개가 필요하다.
- 병렬 Agent 결과를 안전하게 합쳐야 한다.
- 운영 중 문제 발생 시 trace가 필요하다.

### 4.7 Human-in-the-Loop

고위험 업무에는 사용자 또는 운영자 확인이 들어가야 한다.

HITL이 필요한 경우:

- 실제 데이터 변경
- 금전, 권한, 계정, 승인 관련 작업
- 삭제 또는 되돌리기 어려운 작업
- 불확실한 사용자 입력
- 여러 후보 중 선택이 필요한 상황
- 보안 정책상 추가 인증이 필요한 상황

표준 HITL 흐름:

```text
Agent가 실행 준비 완료
  -> 확인 요청 생성
  -> workflow interrupt
  -> 사용자/운영자 입력 대기
  -> resume
  -> 확인/수정/취소/재계획 판단
  -> execute 또는 종료
```

## 5. 표준 디렉터리 구조

신규 프로젝트는 다음 구조를 기본으로 한다.

```text
multi-agent-app/
  README.md
  requirements.txt 또는 pyproject.toml
  .env.example
  main.py

  src/
    agents/
      context.py
      state.py

      supervisor/
        graph.py
        planner.py
        prompts.py
        validators.py

      subagents/
        __init__.py
        <service_defined_agent_1>.py
        <service_defined_agent_2>.py
        <service_defined_agent_3>.py
        tool_agent.py              # 선택 사항: 모델 기반 tool 선택이 필요할 때만 사용
        collaboration.py           # 선택 사항: Agent 간 협업 contract/helper

      a2a/
        cards.py
        schema.py
        routes.py

      tool_calling/
        registry.py
        runner.py
        policy.py
        external.py
        mcp_adapter.py

      common/
        schemas.py
        tracing.py
        llm.py
        parsing.py
        errors.py
        services/

    integrations/
      ports.py
      factory.py
      mock_adapter.py
      external_api_adapter.py

    web/
      routes/

    models/

  tests/
    test_planner.py
    test_supervisor_flow.py
    test_subagents.py
    test_tool_policy.py
    test_a2a_contract.py
    test_hitl_resume.py
    test_readiness.py

  docs/
    architecture.md
    agent_cards.md
    tool_policy.md
    hitl.md
    operations.md
    test_scenarios.md
```

## 6. 개발 수행 단계

### Phase 1. 문제 정의와 Agent 후보 도출

목표:

- 어떤 업무를 Agent화할지 정의한다.

작업:

- 사용자 유형 정의
- 주요 업무 시나리오 정의
- 자동화 가능한 업무와 사람이 개입해야 하는 업무 분리
- Agent 후보 목록 작성
- Tool 후보 목록 작성
- 위험도 분류

산출물:

- 업무 시나리오 목록
- Agent 후보표
- Tool 후보표
- side-effect 분류표

### Phase 2. 표준 아키텍처 설계

목표:

- Supervisor, 서비스별 Sub-Agent 조직도, Tool, Workflow, Agent 간 협업 구조를 확정한다.

작업:

- 전체 workflow diagram 작성
- State/Context 분리
- 서비스 목적에 맞는 Sub-Agent 조직도 작성
- Agent 간 위임/검토/보완/에스컬레이션 관계 정의
- Agent Card 초안 작성
- Agent Collaboration Contract 초안 작성
- Tool Registry 초안 작성
- HITL 지점 정의
- checkpoint 필요 지점 정의

산출물:

- 아키텍처 문서
- Agent 조직도
- Agent Card 명세
- Agent 협업 명세
- State/Context 명세
- Tool Policy 문서

### Phase 3. 최소 실행 골격 구현

목표:

- 실제 업무 로직이 많지 않아도 Agent workflow가 end-to-end로 동작하게 한다.

작업:

- Supervisor graph 구현
- 서비스 목적을 대표하는 최소 2개 Sub-Agent 구현
- 두 Agent 사이의 협업 또는 Supervisor 경유 조정 흐름 1개 구현
- planning schema 구현
- state/context 구현
- 단순 tool registry 구현
- agent activity log 구현

산출물:

- 실행 가능한 minimal agent app
- planner test
- supervisor flow test

### Phase 4. 도메인 업무 구현

목표:

- 실제 업무에 필요한 Agent와 Service를 구현한다.

작업:

- 서비스별 Agent 조직도에 따른 Sub-Agent 구현
- Agent 간 협업 요청/응답 contract 구현
- DB/API/RAG 연동
- deterministic service 분리
- validation rule 구현
- error contract 구현
- 응답 형식 정리

산출물:

- 도메인 Agent
- 도메인 Service
- 통합 테스트

### Phase 5. Tool Calling과 외부 연동

목표:

- 모델이 안전하게 tool을 선택하고 사용할 수 있게 한다.

작업:

- read-only tool 등록
- prepare tool 정책 검토
- external API/MCP adapter 구현
- allowlist 구성
- tool audit event 구현
- redaction 구현
- fallback 구현

산출물:

- Tool Registry
- Tool Policy
- External Tool Adapter
- Tool audit log

### Phase 6. HITL과 실행 통제

목표:

- 고위험 작업을 사용자 확인과 정책 통제 아래 실행한다.

작업:

- interrupt/resume 설계
- confirmation payload schema 구현
- pending action 관리
- 수정/취소/재계획 처리
- execute 단계 분리
- audit log 강화

산출물:

- HITL workflow
- confirmation UI/API
- resume test
- execute policy test

### Phase 7. A2A와 운영 표준화

목표:

- 내부 Agent를 외부 시스템에서도 발견하고 호출할 수 있는 구조를 만든다.

작업:

- Agent Card endpoint 구현
- A2A invoke endpoint 구현
- 인증/권한 정책 적용
- multi-turn task id 설계
- readiness check 작성
- trace/monitoring 구성

산출물:

- A2A endpoint
- readiness report
- operations guide
- monitoring dashboard 기준

## 7. 테스트 전략

표준 테스트는 다음 범주를 포함해야 한다.

| 테스트 | 목적 |
|---|---|
| Planner test | 사용자 요청이 올바른 Agent 계획으로 변환되는지 검증 |
| Agent unit test | 각 Sub-Agent가 독립적으로 동작하는지 검증 |
| Workflow test | Supervisor와 Sub-Agent의 end-to-end 흐름 검증 |
| Collaboration contract test | Agent 간 위임/검토/보완 요청과 응답 schema 검증 |
| HITL resume test | 중단 후 재개가 정확히 동작하는지 검증 |
| Tool policy test | side-effect 정책이 위험 tool을 차단하는지 검증 |
| A2A contract test | Agent Card와 invoke endpoint 계약 검증 |
| Redaction test | 민감정보가 로그에 노출되지 않는지 검증 |
| Readiness test | 운영 배포 전 필수 설정 검증 |

테스트 gold set 예시:

아래 Agent 이름은 예시이며, 실제 테스트에서는 서비스별 Agent 조직도에 맞춘 이름을 사용한다.

```json
[
  {
    "utterance": "최근 문서에서 보안 예외 승인 기준 찾아줘",
    "expected_agents": ["PolicyResearchAgent"],
    "expected_side_effect": "read"
  },
  {
    "utterance": "이 보고서를 요약하고 관련 위험도도 분석해줘",
    "expected_agents": ["ReportWritingAgent", "RiskReviewAgent"],
    "parallel": true
  },
  {
    "utterance": "권한 변경 신청을 제출해줘",
    "expected_agents": ["AccessRequestAgent"],
    "requires_confirmation": true,
    "expected_side_effect": "execute"
  }
]
```

## 8. 운영 기준

운영 가능한 Agent 프로그램은 다음 조건을 만족해야 한다.

- 모든 실행은 trace id를 가진다.
- Supervisor plan이 로그로 남는다.
- 호출된 Agent 목록과 실행 시간이 남는다.
- Tool call은 인자, 결과, 상태가 audit event로 남는다.
- 민감정보는 저장 전 마스킹된다.
- 실패는 원인 코드로 분류된다.
- checkpoint로 multi-turn 상태를 복구할 수 있다.
- 외부 tool은 allowlist 기반으로만 노출된다.
- execute 작업은 사용자 확인 또는 운영자 승인을 거친다.

권장 실패 코드:

- `planner_no_route`
- `planner_policy_violation`
- `agent_timeout`
- `tool_policy_blocked`
- `external_api_error`
- `validation_failed`
- `confirmation_cancelled`
- `checkpoint_resume_failed`
- `redaction_failed`

## 9. 개발 시 주의사항

### 9.1 처음부터 과도하게 추상화하지 않는다

표준 구조는 필요하지만, 첫 구현부터 모든 것을 framework화하면 개발 속도가 느려진다.

권장 방식:

- 먼저 하나의 도메인에서 구조를 완성한다.
- 반복되는 부분을 식별한다.
- Agent Card, Tool Policy, State/Context, Test helper부터 공통화한다.
- 그 다음 scaffold 또는 template으로 분리한다.

### 9.2 실행 업무는 반드시 좁은 경로로 제한한다

조회 Agent는 병렬 실행해도 된다. 그러나 실제 변경이나 실행을 담당하는 Agent는 단일 workflow로 제한해야 한다.

예를 들어 다음 구조는 안전하다.

```text
서비스별 Read/Analysis 계열 Agent들
  -> 병렬 가능

서비스별 실행 권한 Agent
  -> validation
  -> confirmation
  -> execute
  -> audit
  -> 단일 순차 workflow
```

### 9.3 Prompt보다 Contract를 우선한다

Prompt는 중요하지만, 운영 가능한 Agent 시스템에서는 contract가 더 중요하다.

우선순위:

1. Schema
2. Policy
3. Test
4. Prompt

LLM prompt가 아무리 좋아도 schema validation과 policy gate가 없으면 운영 안정성을 보장하기 어렵다.

## 10. 커리어 관점의 정리 방식

이 구조는 개인 포트폴리오나 실무 역량 정리에도 유용하다. 다음과 같이 패턴 이름을 붙여 관리하는 것을 권장한다.

- Supervisor Planning Pattern
- Agent Card Discovery Pattern
- LangGraph Workflow Pattern
- State/Context Separation Pattern
- HITL Checkpoint Pattern
- Tool Side-Effect Policy Pattern
- A2A Internal/External Boundary Pattern
- Deterministic Domain Service Pattern
- Audit-First Tool Calling Pattern
- Planner Validation Pattern

각 패턴마다 다음 항목을 정리하면 좋다.

- 해결하려는 문제
- 적용 조건
- 구조도
- 코드 예시
- 실패 사례
- 테스트 기준
- 운영 기준

이렇게 정리하면 단순히 "Agent를 만들어봤다"가 아니라, "운영 가능한 Multi-AI Agent 아키텍처를 표준화할 수 있다"는 역량으로 설명할 수 있다.

## 11. 최종 권장 방향

표준 Multi-AI Agent 개발의 방향은 다음과 같아야 한다.

- Agent를 많이 만드는 것보다 책임을 명확히 나누는 것이 중요하다.
- LLM 기능을 많이 쓰는 것보다 LLM이 해도 되는 일을 명확히 제한하는 것이 중요하다.
- Tool Calling을 붙이는 것보다 tool policy를 먼저 세우는 것이 중요하다.
- A2A endpoint를 여는 것보다 외부 호출의 권한과 task lifecycle을 먼저 설계하는 것이 중요하다.
- 데모가 동작하는 것보다 checkpoint, audit, redaction, test가 함께 있는 것이 중요하다.

결론적으로, 앞으로 만들 Multi-AI Agent 시스템은 다음 구조를 기본형으로 삼는 것이 좋다.

```text
Supervisor Agent
  -> 계획과 조정

Sub-Agent
  -> 서비스별 업무 조직도에 따라 정의
  -> 독립 수행, 위임, 검토, 보완, 에스컬레이션

Workflow Engine
  -> 상태, 분기, 중단, 재개, 병렬 실행
  -> Agent 간 협업 흐름 관리

Tool Registry
  -> 안전하게 호출 가능한 기능 목록

Policy Layer
  -> 권한, side-effect, 확인, 실행 통제

Observability Layer
  -> trace, audit, readiness, 운영 검증
```

이 구조를 표준으로 잡으면, 특정 도메인이 바뀌어도 Agent 개발 방식은 흔들리지 않는다. 이것이 유지보수성과 확장성을 동시에 확보하는 가장 좋은 방향이다.
