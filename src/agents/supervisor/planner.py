"""
Supervisor planner — 사용자 발화 → ExecutionPlan.

LLM 모드: Agent Card 목록을 Dynamic Prompt 로 받아 구조화 출력(ExecutionPlan) 생성.
폴백   : 결정론적 멀티 인텐트 규칙으로 동일한 계획을 생성.

계획은 "어떤 에이전트를 부를지"까지만 정한다.
실제 금융 검증/실행은 각 에이전트의 결정론적 코드가 수행한다.
"""

from __future__ import annotations

from src.agents.context import BankingContext
from src.agents.common import llm as llm_helper
from src.agents.common import parsing
from src.agents.common.schemas import ExecutionPlan, PlanStep
from src.agents.a2a.cards import render_cards_for_prompt
from src.agents.supervisor.prompts import build_planner_prompt

# 인텐트 → (agent, sub_intent) 매핑 (rule planner)
_INTENT_TO_STEP = {
    "balance_inquiry": ("inquiry", "balance", "잔액/한도 조회 요청"),
    "history_inquiry": ("inquiry", "history", "이체내역 조회 요청"),
    "recurring_inquiry": ("inquiry", "recurring", "자동이체 조회 요청"),
    "recommendation": ("recommend", "recipients", "수신자 추천 요청"),
    "security_inquiry": ("security", "report", "계좌 보안 점검 요청"),
    "menu_search": ("menu_search", "menu", "메뉴/화면 경로 검색 요청"),
    "product_guide": ("product_guide", "guide", "상품/수수료/이용안내 지식 검색 요청"),
    "financial_calculator": ("financial_calculator", "calculate", "금융 계산 요청"),
}

_TOOL_CALLING_PHASE1_AGENTS = {
    "inquiry",
    "recommend",
    "menu_search",
    "product_guide",
    "financial_calculator",
}


def make_plan(ctx: BankingContext, message: str) -> ExecutionPlan:
    """LLM 플래너 시도 → 실패/비활성 시 rule 플래너."""
    plan = None
    if ctx.llm_enabled:
        plan = llm_helper.plan_with_llm(
            ctx, message, build_planner_prompt(ctx, render_cards_for_prompt())
        )
        if plan is not None and _is_sane(plan):
            return _maybe_tool_calling_plan(ctx, plan)
    plan = rule_plan(ctx, message)
    return _maybe_tool_calling_plan(ctx, plan)


def rule_plan(ctx: BankingContext, message: str) -> ExecutionPlan:
    """결정론적 멀티 인텐트 플래너."""
    intents = parsing.detect_intents(message)

    # 이체가 포함되면 transfer 단독 계획 (보안 검증은 transfer 가 자체 협업)
    if "transfer" in intents:
        return ExecutionPlan(
            steps=[PlanStep(agent="transfer", sub_intent="transfer",
                            reason="이체 요청 감지 — 이체 전문 에이전트에 위임")],
            parallel=False,
            primary_intent="transfer",
            planner="rule",
        )

    # "예금 이자 계산"처럼 상품 단어가 섞여도 숫자 산출이 목적이면 계산 Agent가 우선이다.
    # 상품/수수료 설명은 사용자가 별도로 안내를 요청할 때 product_guide가 담당한다.
    if "financial_calculator" in intents:
        intents = [i for i in intents if i != "product_guide"]

    steps = []
    for intent in intents:
        if intent in _INTENT_TO_STEP:
            agent, sub, reason = _INTENT_TO_STEP[intent]
            steps.append(PlanStep(agent=agent, sub_intent=sub, reason=reason))

    # 보안 강화 대상 고객: 조회 계획에 보안 리포트 동반 (Dynamic planning)
    if steps and ctx.risk_profile == "high" and not any(s.agent == "security" for s in steps):
        steps.append(PlanStep(agent="security", sub_intent="report",
                              reason="보안 강화 대상 고객 — 보안 점검 동반 수행"))

    if not steps:
        return ExecutionPlan(steps=[], parallel=False, primary_intent="unknown", planner="rule")

    return ExecutionPlan(
        steps=steps,
        parallel=len(steps) > 1,
        primary_intent=intents[0],
        planner="rule",
        note=f"{len(steps)}개 작업 {'병렬' if len(steps) > 1 else '단일'} 실행",
    )


def _is_sane(plan: ExecutionPlan) -> bool:
    """LLM 계획의 최소 안전성 검사 — 이체는 반드시 단독 step."""
    agents = [s.agent for s in plan.steps]
    if "transfer" in agents and len(agents) > 1:
        return False
    return True


def _maybe_tool_calling_plan(ctx: BankingContext, plan: ExecutionPlan) -> ExecutionPlan:
    """Collapse Phase 1 read-only work into one OpenAI tool-calling agent turn."""
    if not getattr(ctx, "tool_calling_enabled", False):
        return plan
    if not ctx.llm_enabled:
        return plan
    if not plan.steps:
        return plan
    if _is_transfer_prep_candidate(ctx, plan):
        return ExecutionPlan(
            steps=[
                PlanStep(
                    agent="tool_agent",
                    sub_intent="transfer_prep_tools",
                    reason="OpenAI Tool Calling으로 이체 준비 정보를 사전 정리",
                )
            ],
            parallel=False,
            primary_intent=plan.primary_intent,
            planner=f"{plan.planner}+tool_calling_transfer_prep",
            note="Phase 2 transfer-prep tool-calling plan; execution remains blocked",
        )
    if any(step.agent not in _TOOL_CALLING_PHASE1_AGENTS for step in plan.steps):
        return plan

    return ExecutionPlan(
        steps=[
            PlanStep(
                agent="tool_agent",
                sub_intent="read_only_tools",
                reason="OpenAI Tool Calling으로 읽기 전용 업무 도구를 직접 선택",
            )
        ],
        parallel=False,
        primary_intent=plan.primary_intent,
        planner=f"{plan.planner}+tool_calling",
        note=f"Phase 1 tool-calling plan; original_steps={len(plan.steps)}",
    )


def _is_transfer_prep_candidate(ctx: BankingContext, plan: ExecutionPlan) -> bool:
    return (
        bool(getattr(ctx, "tool_calling_transfer_prep_enabled", False))
        and len(plan.steps) == 1
        and plan.steps[0].agent == "transfer"
    )
