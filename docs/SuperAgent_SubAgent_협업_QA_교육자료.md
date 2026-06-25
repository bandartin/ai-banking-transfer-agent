# Super Agent와 Sub-Agent 협업 구조 Q&A

이 문서는 현재 코드 기준으로 Super Agent가 어떻게 계획을 세우고 Sub-Agent를 호출하는지, 그리고 Sub-Agent 간 협업이 Super Agent를 거치지 않고 어떻게 직접 이루어지는지 설명하기 위한 교육용 자료입니다.

핵심 질문은 두 가지입니다.

1. Super Agent는 사용자 요청을 어떻게 계획으로 바꾸고, Sub-Agent를 어떻게 호출하는가?
2. Sub-Agent끼리는 어떤 경우에 Super Agent를 거치지 않고 직접 호출하는가?

현재 코드에서 답은 다음과 같습니다.

```text
일반 사용자 요청
  -> Supervisor plan
  -> ExecutionPlan 생성
  -> route_plan에서 Send로 Sub-Agent 호출
  -> respond에서 결과 집계

이체 중 보안 평가
  -> TransferAgent 내부 validate_and_secure_node
  -> SecurityAgent subgraph 직접 invoke
  -> risk_assessment를 받아 이체 확인/OTP 흐름에 반영

외부 A2A 단독 호출
  -> /api/a2a/agents/<agent_key>/invoke
  -> inquiry/recommend/security subgraph 직접 invoke
  -> transfer는 HITL 때문에 supervisor 경유만 허용
```

---

## 1. Q. 이 프로젝트에서 Super Agent는 무엇인가요?

이 프로젝트에서 Super Agent는 `Supervisor`입니다.

코드 위치:

- `src/agents/supervisor/graph.py`
- `src/agents/supervisor/planner.py`

Supervisor의 역할은 사용자의 자연어 요청을 바로 실행하는 것이 아니라, 먼저 실행 계획인 `ExecutionPlan`으로 바꾸는 것입니다.

예를 들어 사용자가 이렇게 말한다고 가정합니다.

```text
잔고 보여주고 자주 보내는 사람도 추천해줘
```

Supervisor는 이 요청을 하나의 응답으로 바로 만들지 않습니다. 대신 다음과 같은 계획으로 나눕니다.

```text
1. InquiryAgent에게 balance 조회 요청
2. RecommendAgent에게 recipients 추천 요청
3. 두 결과를 모아서 최종 응답 생성
```

즉 Supervisor는 실제 금융 업무를 직접 처리하기보다, 어떤 Sub-Agent에게 어떤 일을 맡길지 결정하는 orchestrator입니다.

---

## 2. Q. Super Agent 그래프는 어떻게 생겼나요?

Supervisor graph는 `build_banking_graph()`에서 구성됩니다.

```python
def build_banking_graph(checkpointer=None):
    g = StateGraph(BankingState, context_schema=BankingContext)

    g.add_node("plan", plan_node)
    g.add_node("transfer", build_transfer_subgraph())
    g.add_node("inquiry", build_inquiry_subgraph())
    g.add_node("recommend", build_recommend_subgraph())
    g.add_node("security", build_security_subgraph())
    g.add_node("respond", respond_node)

    g.add_edge(START, "plan")
    g.add_conditional_edges(
        "plan", route_plan,
        ["transfer", "inquiry", "recommend", "security", "respond"],
    )
    g.add_edge("transfer", "respond")
    g.add_edge("inquiry", "respond")
    g.add_edge("recommend", "respond")
    g.add_edge("security", "respond")
    g.add_edge("respond", END)

    return g.compile(checkpointer=checkpointer)
```

중요한 점은 Sub-Agent들이 단순 함수가 아니라 각각 독립적으로 컴파일된 subgraph라는 것입니다.

```text
Supervisor graph
  plan
    -> transfer subgraph
    -> inquiry subgraph
    -> recommend subgraph
    -> security subgraph
  respond
```

따라서 Supervisor는 Sub-Agent를 "함수 호출"처럼 부르는 것이 아니라, LangGraph node로 등록된 subgraph를 실행합니다.

---

## 3. Q. Super Agent는 계획을 어떻게 세우나요?

계획 생성은 `plan_node()`에서 시작됩니다.

```python
@traced("supervisor", "plan")
def plan_node(state: dict, runtime: Runtime[BankingContext]) -> dict:
    ctx = runtime.context
    message = state.get("current_message", "")

    plan = make_plan(ctx, message)

    return {
        "plan": plan.model_dump(),
        "intent": plan.primary_intent,
        "agent_activity": [activity("supervisor", "plan", {
            "planner": plan.planner,
            "parallel": plan.parallel,
            "steps": [
                {"agent": s.agent, "sub_intent": s.sub_intent, "reason": s.reason}
                for s in plan.steps
            ],
            "note": plan.note,
        })],
    }
```

여기서 중요한 흐름은 단순합니다.

```text
current_message 추출
  -> make_plan(ctx, message)
  -> ExecutionPlan 생성
  -> plan을 State에 저장
```

`make_plan()`은 LLM planner를 먼저 시도하고, 실패하거나 사용할 수 없으면 rule planner로 fallback합니다.

```python
def make_plan(ctx: BankingContext, message: str) -> ExecutionPlan:
    if ctx.llm_enabled:
        plan = llm_helper.plan_with_llm(
            ctx, message, build_planner_prompt(ctx, render_cards_for_prompt())
        )
        if plan is not None and _is_sane(plan):
            return plan
    return rule_plan(ctx, message)
```

즉 구조는 다음과 같습니다.

```text
LLM 사용 가능
  -> Agent Card 목록을 prompt에 넣고 structured plan 생성 시도
  -> plan이 안전하면 사용

LLM 미사용 또는 실패
  -> rule_plan으로 결정론적 계획 생성
```

---

## 4. Q. ExecutionPlan은 어떤 모양인가요?

계획 schema는 `src/agents/common/schemas.py`에 있습니다.

```python
AgentName = Literal["transfer", "inquiry", "recommend", "security"]

class PlanStep(BaseModel):
    agent: AgentName
    sub_intent: str
    reason: str = ""

class ExecutionPlan(BaseModel):
    steps: List[PlanStep] = Field(default_factory=list)
    parallel: bool = False
    primary_intent: str = "unknown"
    planner: str = "rule"
    note: str = ""
```

예를 들어 잔고 조회만 하면 이런 계획이 됩니다.

```python
ExecutionPlan(
    steps=[
        PlanStep(agent="inquiry", sub_intent="balance", reason="잔액/한도 조회 요청")
    ],
    parallel=False,
    primary_intent="balance_inquiry",
    planner="rule",
)
```

복합 요청이면 여러 step이 생깁니다.

```python
ExecutionPlan(
    steps=[
        PlanStep(agent="inquiry", sub_intent="balance", reason="잔액/한도 조회 요청"),
        PlanStep(agent="recommend", sub_intent="recipients", reason="수신자 추천 요청"),
    ],
    parallel=True,
    primary_intent="balance_inquiry",
    planner="rule",
)
```

핵심은 `steps`입니다. Supervisor는 이 `steps`를 보고 어떤 Sub-Agent를 호출할지 결정합니다.

---

## 5. Q. rule planner는 어떤 기준으로 agent를 고르나요?

`rule_plan()`은 먼저 사용자 발화에서 intent 목록을 감지합니다.

```python
def rule_plan(ctx: BankingContext, message: str) -> ExecutionPlan:
    intents = parsing.detect_intents(message)
```

그 다음 intent와 agent/sub_intent 매핑을 사용합니다.

```python
_INTENT_TO_STEP = {
    "balance_inquiry": ("inquiry", "balance", "잔액/한도 조회 요청"),
    "history_inquiry": ("inquiry", "history", "이체내역 조회 요청"),
    "recurring_inquiry": ("inquiry", "recurring", "자동이체 조회 요청"),
    "recommendation": ("recommend", "recipients", "수신자 추천 요청"),
    "security_inquiry": ("security", "report", "계좌 보안 평가 요청"),
}
```

이체 요청은 별도 처리됩니다.

```python
if "transfer" in intents:
    return ExecutionPlan(
        steps=[PlanStep(agent="transfer", sub_intent="transfer",
                        reason="이체 요청 감지 → 이체 전문 에이전트에 위임")],
        parallel=False,
        primary_intent="transfer",
        planner="rule",
    )
```

이체가 들어오면 transfer 단독 계획으로 제한합니다.

이유는 명확합니다.

```text
이체는 확인, OTP, 검증, DB 변경이 있는 고위험 workflow다.
따라서 balance/recommend/security 같은 read-only 작업과 병렬로 섞지 않는다.
```

LLM planner도 이 안전 규칙을 통과해야 합니다.

```python
def _is_sane(plan: ExecutionPlan) -> bool:
    agents = [s.agent for s in plan.steps]
    if "transfer" in agents and len(agents) > 1:
        return False
    return True
```

---

## 6. Q. 계획이 만들어진 뒤 Sub-Agent는 어떻게 호출되나요?

계획 이후의 routing은 `route_plan()`에서 합니다.

```python
def route_plan(state: dict) -> Union[str, list]:
    plan = state.get("plan") or {}
    steps = plan.get("steps") or []

    if not steps:
        return "respond"

    sends = []
    for step in steps:
        sends.append(Send(step["agent"], {
            "user_id": state["user_id"],
            "session_id": state.get("session_id", ""),
            "current_message": state.get("current_message", ""),
            "intent": plan.get("primary_intent", ""),
            "sub_intent": step["sub_intent"],
        }))
    return sends
```

여기서 `Send(step["agent"], payload)`가 핵심입니다.

예를 들어 계획이 다음과 같다면:

```text
steps:
  - agent: inquiry, sub_intent: balance
  - agent: recommend, sub_intent: recipients
```

`route_plan()`은 대략 이런 Send 목록을 반환합니다.

```python
[
    Send("inquiry", {
        "user_id": 1,
        "session_id": "...",
        "current_message": "잔고 보여주고 자주 보내는 사람 추천해줘",
        "intent": "balance_inquiry",
        "sub_intent": "balance",
    }),
    Send("recommend", {
        "user_id": 1,
        "session_id": "...",
        "current_message": "잔고 보여주고 자주 보내는 사람 추천해줘",
        "intent": "balance_inquiry",
        "sub_intent": "recipients",
    }),
]
```

LangGraph는 이 Send를 보고 해당 node, 즉 등록된 Sub-Agent subgraph를 실행합니다.

---

## 7. Q. Send를 쓰면 순차 호출인가요, 병렬 호출인가요?

현재 `route_plan()`은 모든 step을 `Send` 목록으로 반환합니다. LangGraph 관점에서는 fan-out 형태입니다.

따라서 조회와 추천처럼 서로 독립적인 작업은 병렬로 실행될 수 있습니다.

예:

```text
사용자: 잔고 보여주고 자주 보내는 사람 추천해줘

Supervisor plan:
  - inquiry(balance)
  - recommend(recipients)

route_plan:
  - Send("inquiry", ...)
  - Send("recommend", ...)

결과:
  - InquiryAgent 결과
  - RecommendAgent 결과
  -> respond에서 집계
```

단, transfer가 포함되면 planner 단계에서 단독 step으로 제한하므로 병렬 fan-out에 섞이지 않습니다.

---

## 8. Q. Sub-Agent는 어떤 입력을 받나요?

Supervisor가 Send로 넘기는 payload는 일부 State입니다.

```python
{
    "user_id": state["user_id"],
    "session_id": state.get("session_id", ""),
    "current_message": state.get("current_message", ""),
    "intent": plan.get("primary_intent", ""),
    "sub_intent": step["sub_intent"],
}
```

여기서 가장 중요한 값은 `sub_intent`입니다.

Sub-Agent는 같은 graph라도 `sub_intent`에 따라 다른 일을 합니다.

예를 들어 InquiryAgent는 하나의 `inquiry_node()` 안에서 다음처럼 분기합니다.

```python
sub = state.get("sub_intent") or "balance"

if sub == "history":
    result = _history(user_id)
elif sub == "recurring":
    result = _recurring(user_id)
else:
    result = _balance(user_id)
```

즉 Supervisor는 "InquiryAgent를 호출해"가 아니라 "InquiryAgent에게 balance 일을 시켜"라고 더 구체적인 지시를 내립니다.

---

## 9. Q. Sub-Agent 결과는 어떻게 Supervisor로 돌아오나요?

Sub-Agent는 보통 `agent_results`에 결과를 넣습니다.

InquiryAgent 예:

```python
return {
    "agent_results": [{"agent": "inquiry", "kind": sub, **result}],
    "agent_activity": [activity("inquiry", f"{sub}_done")],
}
```

RecommendAgent 예:

```python
return {
    "agent_results": [{
        "agent": "recommend", "kind": "recipients",
        "text": "\n".join(lines),
        "data": {"recommendations": rec_list},
    }],
    "agent_activity": [activity("recommend", "done", {"count": len(rec_list)})],
}
```

`BankingState`에서 `agent_results`는 누적 reducer를 사용합니다.

```python
agent_results: Annotated[List[Dict[str, Any]], _accumulate]
```

그래서 여러 Sub-Agent가 병렬로 결과를 반환해도 `agent_results` 리스트에 합쳐집니다.

---

## 10. Q. 최종 응답은 누가 만드나요?

최종 응답은 `respond_node()`가 만듭니다.

```python
@traced("supervisor", "respond")
def respond_node(state: dict, runtime: Runtime[BankingContext]) -> dict:
    ctx = runtime.context
    results = state.get("agent_results") or []
    plan = state.get("plan") or {}
    steps = plan.get("steps") or []
```

먼저 `agent_results`를 가져오고, 계획 순서에 맞게 정렬합니다.

```python
def _order(entry: dict) -> int:
    for i, s in enumerate(steps):
        if s["agent"] == entry.get("agent") and s["sub_intent"] == entry.get("kind"):
            return i
        if s["agent"] == entry.get("agent"):
            return i
    return len(steps)

results = sorted(results, key=_order)
```

그 다음 각 결과의 text를 합칩니다.

```python
text = "\n\n".join(r.get("text", "") for r in results if r.get("text"))
```

여러 결과가 있으면 response_data도 kind별로 묶습니다.

```python
if len(results) == 1:
    response_data = primary.get("data")
else:
    response_data = {r.get("kind", f"r{i}"): r.get("data") for i, r in enumerate(results)}
```

정리하면:

```text
Sub-Agent들이 agent_results 반환
  -> BankingState reducer가 결과 누적
  -> respond_node가 계획 순서대로 정렬
  -> text와 data를 최종 응답으로 구성
```

---

## 11. Q. Sub-Agent 간 협업은 실제로 어디에서 발생하나요?

가장 중요한 Sub-Agent 간 협업은 TransferAgent와 SecurityAgent 사이에서 발생합니다.

코드 위치:

- `src/agents/subagents/transfer.py`
- `src/agents/subagents/security.py`

흐름은 다음과 같습니다.

```text
TransferAgent
  -> 수신자/금액 해석
  -> 이체 summary 생성
  -> 기본 검증
  -> SecurityAgent 직접 호출
  -> risk_assessment 수신
  -> OTP 필요 여부와 warning 반영
  -> confirm interrupt로 사용자 확인 요청
```

이때 SecurityAgent 호출은 Supervisor를 타지 않습니다.

---

## 12. Q. TransferAgent는 SecurityAgent를 어떻게 직접 호출하나요?

TransferAgent의 `validate_and_secure_node()`가 SecurityAgent를 직접 호출합니다.

```python
from src.agents.subagents.security import get_security_graph
```

그 다음 SecurityAgent에 넘길 입력을 만듭니다.

```python
sec_input = {
    "user_id": user_id,
    "session_id": state.get("session_id", ""),
    "pending_transfer_data": summary.model_dump(),
}
```

그리고 직접 invoke합니다.

```python
sec_out = get_security_graph().invoke(sec_input, context=ctx)
assessment = sec_out.get("risk_assessment") or {}
```

이 부분이 "Super Agent를 거치지 않는 Sub-Agent 간 직접 호출"의 핵심입니다.

```text
Supervisor -> TransferAgent
TransferAgent -> SecurityAgent
SecurityAgent -> TransferAgent
TransferAgent -> confirm
```

Supervisor가 다시 중간에 개입하지 않습니다.

---

## 13. Q. 왜 TransferAgent가 SecurityAgent를 직접 호출하나요?

이체 workflow 안에서 보안 평가는 중간 검증 단계입니다.

사용자 관점에서는 "보안 평가해줘"가 아니라 "이체해줘"라고 요청했습니다. 하지만 시스템 내부적으로는 이체 실행 전에 보안 평가가 필요합니다.

이 경우 보안 평가는 독립 사용자 요청이라기보다 TransferAgent의 내부 협업 요청입니다.

따라서 Supervisor가 다시 계획을 짜게 하는 것보다, TransferAgent가 필요한 시점에 SecurityAgent를 직접 호출하는 것이 더 자연스럽습니다.

장점:

1. 이체 workflow의 책임 경계가 명확합니다.
2. 보안 평가가 confirm 직전에 항상 수행됩니다.
3. SecurityAgent의 rule을 재사용하면서도 이체 흐름이 끊기지 않습니다.
4. Supervisor가 모든 세부 검증 단계를 알 필요가 없습니다.

실무적으로는 다음 구조가 좋습니다.

```text
Supervisor는 "누가 큰 일을 맡을지" 결정한다.
Sub-Agent는 자기 업무 안에서 필요한 전문 Agent와 협업한다.
```

---

## 14. Q. SecurityAgent는 직접 호출될 때와 Supervisor가 부를 때 다르게 동작하나요?

네. 같은 SecurityAgent지만 입력 State에 따라 모드가 달라집니다.

SecurityAgent의 `assess_node()`는 먼저 `pending_transfer_data`가 있는지 봅니다.

```python
pending = state.get("pending_transfer_data")

if pending:
    summary = TransferSummary(**pending)
    assessment = security_rules.assess_transfer(ctx, user_id, summary)
    return {
        "risk_assessment": assessment.model_dump(),
        "agent_activity": [...]
    }
```

`pending_transfer_data`가 있으면 이체 1건에 대한 리스크 평가 모드입니다.

이 모드는 TransferAgent가 직접 호출할 때 사용합니다.

반대로 `pending_transfer_data`가 없으면 보안 리포트 모드입니다.

```python
report = security_rules.security_report(ctx, user_id)

return {
    "agent_results": [{
        "agent": "security",
        "kind": "security_report",
        "text": text,
        "data": report,
    }],
    "agent_activity": [...]
}
```

이 모드는 사용자가 "내 계좌 안전한지 봐줘"처럼 말했을 때 Supervisor가 `security(report)`로 호출하는 경로입니다.

정리하면:

| 호출 경로 | 입력 | SecurityAgent 동작 | 반환 |
|---|---|---|---|
| TransferAgent 직접 호출 | `pending_transfer_data` 있음 | 이체 리스크 평가 | `risk_assessment` |
| Supervisor 호출 | `pending_transfer_data` 없음, `sub_intent=report` | 보안 리포트 생성 | `agent_results` |

---

## 15. Q. SecurityAgent 결과는 TransferAgent에서 어떻게 쓰이나요?

TransferAgent는 SecurityAgent 결과에서 `risk_assessment`를 꺼냅니다.

```python
assessment = sec_out.get("risk_assessment") or {}
```

그리고 OTP 필요 여부를 계산합니다.

```python
requires_otp = summary.requires_otp or bool(assessment.get("force_otp"))
warnings = result.warnings + list(assessment.get("warnings", []))
```

그 결과를 `pending_transfer_data`에 반영합니다.

```python
summary_dict = summary.model_dump()
summary_dict["requires_otp"] = requires_otp
summary_dict["warnings"] = warnings
```

마지막으로 다음 node를 `confirm`으로 지정합니다.

```python
return Command(goto="confirm", update={
    "pending_transfer_data": summary_dict,
    "risk_assessment": assessment,
    ...
})
```

즉 SecurityAgent는 직접 송금을 막거나 실행하지 않습니다. 리스크 평가 정보를 제공하고, TransferAgent가 그 결과를 이체 workflow에 반영합니다.

역할 분리가 잘 되어 있습니다.

```text
SecurityAgent: 위험도를 평가한다.
TransferAgent: 평가 결과를 이체 확인/OTP 흐름에 반영한다.
```

---

## 16. Q. 외부에서 Super Agent를 거치지 않고 Sub-Agent를 직접 호출할 수도 있나요?

네. A2A route를 통해 일부 Sub-Agent는 직접 호출할 수 있습니다.

코드 위치:

- `src/web/routes/a2a.py`
- `src/agents/a2a/cards.py`

외부 endpoint는 다음 형태입니다.

```text
POST /api/a2a/agents/<agent_key>/invoke
```

`invoke_agent()`는 agent key에 따라 동작합니다.

Supervisor 호출이면 전체 pipeline에 위임합니다.

```python
if agent_key == "supervisor":
    from src.agents.supervisor import run_banking_agent
    result = run_banking_agent(user_id=user_id, message=text, session_id=ctx.session_id)
```

Sub-Agent 단독 호출이면 builder를 고릅니다.

```python
builders = {
    "inquiry": build_inquiry_subgraph,
    "recommend": build_recommend_subgraph,
    "security": build_security_subgraph,
}

graph = builders[agent_key]()
out = graph.invoke(
    {
        "user_id": user_id,
        "session_id": ctx.session_id,
        "current_message": text,
        "sub_intent": meta.get("sub_intent", ""),
    },
    context=ctx,
)
```

이 경로는 Supervisor를 통하지 않고 Sub-Agent graph를 직접 만들어 invoke합니다.

---

## 17. Q. 그런데 왜 transfer는 A2A 직접 호출을 막나요?

`a2a.py`에는 transfer 직접 호출을 막는 코드가 있습니다.

```python
if agent_key == "transfer":
    return _rpc_error(
        body, -32600,
        "transfer 에이전트는 Human-in-the-Loop(확인/OTP)가 필요하므로 supervisor 경유로만 호출 가능합니다.",
    )
```

이것은 의도적인 안전 설계입니다.

이체는 단발성 stateless 호출로 끝나지 않습니다.

```text
수신자 해석
  -> 금액 확인
  -> 검증
  -> 보안 평가
  -> 사용자 확인 interrupt
  -> OTP interrupt
  -> 실행
```

이 흐름은 checkpoint, thread_id, interrupt resume이 함께 관리되어야 합니다.

외부 client가 TransferAgent를 직접 호출하면 확인/OTP 같은 HITL protocol을 제대로 처리하지 못할 수 있습니다.

따라서 현재 구조에서는:

```text
inquiry/recommend/security -> 직접 A2A 호출 허용
transfer -> supervisor 경유만 허용
```

이 판단은 안전한 선택입니다.

---

## 18. Q. 내부 직접 호출과 외부 A2A 직접 호출은 무엇이 다른가요?

둘 다 "Supervisor를 거치지 않는다"는 점은 같습니다. 하지만 목적이 다릅니다.

| 구분 | 내부 직접 호출 | 외부 A2A 직접 호출 |
|---|---|---|
| 예 | TransferAgent -> SecurityAgent | 외부 client -> InquiryAgent |
| 코드 위치 | `transfer.py` | `a2a.py` |
| 호출 방식 | `get_security_graph().invoke(...)` | HTTP JSON-RPC style invoke |
| 목적 | workflow 내부 협업 | 외부 시스템의 agent 단독 사용 |
| 상태 | parent workflow 안의 일부 | stateless 단독 호출에 가까움 |
| 허용 agent | 현재 SecurityAgent | inquiry, recommend, security |

내부 직접 호출은 업무 흐름의 일부입니다. 외부 A2A 직접 호출은 공개된 agent capability를 호출하는 인터페이스입니다.

---

## 19. Q. Agent Card는 어디에 쓰이나요?

Agent Card는 각 Sub-Agent의 capability metadata입니다.

코드 위치:

- `src/agents/a2a/cards.py`

`AGENT_CARDS`에는 각 agent의 이름, 설명, skill, 예시, 협업 대상이 정의되어 있습니다.

```python
AGENT_CARDS: dict[str, dict] = {
    "transfer": {
        "name": "TransferAgent",
        "skills": [...],
        "collaborates_with": ["security"],
    },
    "inquiry": {...},
    "recommend": {...},
    "security": {...},
}
```

이 정보는 두 방향으로 쓰입니다.

1. 내부적으로 LLM planner prompt에 agent 목록을 넣을 때 사용합니다.
2. 외부적으로 A2A discovery endpoint에서 agent card를 노출할 때 사용합니다.

LLM planner에는 `render_cards_for_prompt()`가 들어갑니다.

```python
plan = llm_helper.plan_with_llm(
    ctx, message, build_planner_prompt(ctx, render_cards_for_prompt())
)
```

외부에는 다음 endpoint로 노출됩니다.

```text
GET /.well-known/agent-card.json
GET /api/a2a/agents
GET /api/a2a/agents/<agent_key>
```

즉 Agent Card는 "내부 planner가 참고하는 agent catalog"이면서 "외부 시스템이 발견할 수 있는 capability 명세"입니다.

---

## 20. Q. 전체 흐름을 하나의 예로 보면?

예시 요청:

```text
잔고 보여주고 자주 보내는 사람 추천해줘
```

흐름:

```text
1. Flask route가 run_banking_agent() 호출
2. Supervisor graph invoke
3. plan_node가 make_plan() 호출
4. rule_plan이 intents 감지
5. ExecutionPlan 생성
   - inquiry(balance)
   - recommend(recipients)
6. route_plan이 Send 목록 반환
7. InquiryAgent와 RecommendAgent 실행
8. 각 agent가 agent_results 반환
9. respond_node가 결과를 계획 순서대로 합침
10. 최종 응답 반환
```

이체 요청:

```text
엄마에게 5만원 보내줘
```

흐름:

```text
1. plan_node가 transfer 단독 계획 생성
2. route_plan이 Send("transfer", ...) 반환
3. TransferAgent subgraph 실행
4. 수신자/금액 해석
5. validate_and_secure_node에서 SecurityAgent 직접 invoke
6. risk_assessment 반영
7. confirm_node에서 interrupt 발생
8. 사용자 확인 후 execute 또는 OTP 진행
```

---

## 21. Q. 이 구조의 설계 포인트는 무엇인가요?

첫째, Supervisor는 너무 많은 일을 하지 않습니다.

Supervisor는 계획, dispatch, 응답 집계를 담당합니다. 실제 업무 규칙은 Sub-Agent와 service layer가 맡습니다.

둘째, Sub-Agent는 독립 graph입니다.

각 agent는 `StateGraph(BankingState)`로 구성되고, Supervisor에 node로 합성됩니다. 그래서 단독 호출도 가능하고, 상위 orchestration에도 참여할 수 있습니다.

셋째, 위험도가 높은 transfer는 단독 A2A 호출을 제한합니다.

이체는 HITL과 checkpoint가 필요한 장기 workflow이므로 supervisor 경유로 통제합니다.

넷째, 내부 협업은 필요한 곳에서 직접 합니다.

TransferAgent가 보안 평가가 필요한 시점에 SecurityAgent를 직접 호출합니다. 이건 사용자 요청의 재계획이 아니라 workflow 내부 검증이기 때문입니다.

---

## 22. 팀원에게 한 문장으로 설명하면

> Supervisor는 사용자 발화를 ExecutionPlan으로 바꿔 Sub-Agent subgraph들을 Send로 호출하고, Sub-Agent 간 협업이 필요한 경우에는 TransferAgent가 SecurityAgent를 직접 invoke해 리스크 평가 결과를 자신의 이체 workflow에 반영한다.

---

## 23. 코드에서 볼 위치

| 주제 | 파일 |
|---|---|
| Supervisor graph 구성 | `src/agents/supervisor/graph.py` |
| plan node | `src/agents/supervisor/graph.py` |
| route_plan과 Send dispatch | `src/agents/supervisor/graph.py` |
| respond node 결과 집계 | `src/agents/supervisor/graph.py` |
| ExecutionPlan schema | `src/agents/common/schemas.py` |
| rule/LLM planner | `src/agents/supervisor/planner.py` |
| Agent Card | `src/agents/a2a/cards.py` |
| A2A 직접 호출 route | `src/web/routes/a2a.py` |
| TransferAgent -> SecurityAgent 직접 호출 | `src/agents/subagents/transfer.py` |
| SecurityAgent assess/report dual mode | `src/agents/subagents/security.py` |
| InquiryAgent sub_intent 분기 | `src/agents/subagents/inquiry.py` |
| RecommendAgent 단독 subgraph | `src/agents/subagents/recommend.py` |
