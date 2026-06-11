"""
LLM 팩토리 — Runtime context 기반으로 OpenAI 모델을 생성하고,
키가 없거나 호출이 실패하면 결정론적 파서로 폴백한다.

LLM 의 역할은 ①이해(인텐트/슬롯) ②계획(Supervisor planning) ③표현(말투 다듬기)
까지이며, 검증·실행 같은 금융 결정에는 절대 관여하지 않는다.
"""

from __future__ import annotations

from typing import Optional

from src.agents.context import BankingContext
from src.agents.common import parsing
from src.agents.common.schemas import ExecutionPlan, ExtractedSlots


def get_chat_model(ctx: BankingContext, temperature: float = 0.0):
    """Return a ChatOpenAI instance, or None when LLM is unavailable."""
    if not ctx.llm_enabled:
        return None
    try:
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(model=ctx.openai_model, api_key=ctx.openai_api_key, temperature=temperature)
    except Exception:
        return None


# ─────────────────────────────────────────────────────────────────────────────
# Structured helpers (LLM with deterministic fallback)
# ─────────────────────────────────────────────────────────────────────────────


def extract_slots(ctx: BankingContext, text: str, system_prompt: str) -> ExtractedSlots:
    """슬롯 추출 — LLM 구조화 출력, 실패 시 결정론적 파서."""
    llm = get_chat_model(ctx)
    if llm is not None:
        try:
            structured = llm.with_structured_output(ExtractedSlots)
            return structured.invoke([("system", system_prompt), ("user", text)])
        except Exception:
            pass
    return parsing.extract_slots(text)


def plan_with_llm(ctx: BankingContext, text: str, system_prompt: str) -> Optional[ExecutionPlan]:
    """Supervisor planning — LLM 구조화 출력. 실패 시 None (rule planner 폴백)."""
    llm = get_chat_model(ctx)
    if llm is None:
        return None
    try:
        structured = llm.with_structured_output(ExecutionPlan)
        plan = structured.invoke([("system", system_prompt), ("user", text)])
        plan.planner = "llm"
        return plan
    except Exception:
        return None


def polish_response(ctx: BankingContext, draft: str, system_prompt: str) -> str:
    """응답 말투 다듬기 — 사실(숫자/계좌)은 유지하고 표현만 조정. 실패 시 원문."""
    llm = get_chat_model(ctx, temperature=0.3)
    if llm is None:
        return draft
    try:
        resp = llm.invoke([("system", system_prompt), ("user", draft)])
        out = (resp.content or "").strip()
        return out or draft
    except Exception:
        return draft
