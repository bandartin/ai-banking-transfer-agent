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
from src.awx_runtime.observability import llm_call


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
    rule_slots = parsing.extract_slots(text)
    llm = get_chat_model(ctx)
    if llm is not None:
        try:
            structured = llm.with_structured_output(ExtractedSlots)
            with llm_call(ctx, "slot_extraction", text) as awx_log:
                llm_slots = structured.invoke([("system", system_prompt), ("user", text)])
                awx_log.output_message = llm_slots.model_dump_json()
            return _cross_check_slots(llm_slots, rule_slots)
        except Exception:
            pass
    return rule_slots


def _cross_check_slots(llm_slots: ExtractedSlots, rule_slots: ExtractedSlots) -> ExtractedSlots:
    """Merge LLM understanding with deterministic parser evidence.

    금융 실행에 직접 영향을 주는 금액은 Rule 값과 충돌하면 Rule 값을 우선한다.
    수신자/메모/힌트는 LLM 값을 활용하되 충돌 사실을 디버그 가능한 필드에 남긴다.
    """
    data = llm_slots.model_dump()
    ambiguous = set(data.get("ambiguous_fields") or [])
    evidence = dict(rule_slots.evidence or {})
    evidence.update(data.get("evidence") or {})

    data["extraction_method"] = "llm+rule_cross_check"

    if rule_slots.raw_amount_text and not data.get("raw_amount_text"):
        data["raw_amount_text"] = rule_slots.raw_amount_text
    if rule_slots.recipient_text and not data.get("recipient_text"):
        data["recipient_text"] = rule_slots.recipient_text
    if rule_slots.bank_hint and not data.get("bank_hint"):
        data["bank_hint"] = rule_slots.bank_hint
    if rule_slots.source_account_hint and not data.get("source_account_hint"):
        data["source_account_hint"] = rule_slots.source_account_hint

    if llm_slots.amount and rule_slots.amount and llm_slots.amount != rule_slots.amount:
        data["amount"] = rule_slots.amount
        ambiguous.add("amount")
        evidence["amount_conflict"] = f"llm={llm_slots.amount}, rule={rule_slots.amount}"
    elif not llm_slots.amount and rule_slots.amount:
        data["amount"] = rule_slots.amount
    elif llm_slots.amount and not rule_slots.amount:
        ambiguous.add("amount")
        evidence["amount_unverified_by_rule"] = str(llm_slots.amount)

    if llm_slots.recipient_alias and rule_slots.recipient_alias and llm_slots.recipient_alias != rule_slots.recipient_alias:
        ambiguous.add("recipient_alias")
        evidence["recipient_conflict"] = f"llm={llm_slots.recipient_alias}, rule={rule_slots.recipient_alias}"
    elif not llm_slots.recipient_alias and rule_slots.recipient_alias:
        data["recipient_alias"] = rule_slots.recipient_alias

    for field in ("memo", "recurring_hint", "bank_hint", "source_account_hint"):
        if not data.get(field) and getattr(rule_slots, field):
            data[field] = getattr(rule_slots, field)

    missing = set(data.get("missing_fields") or [])
    missing.update(rule_slots.missing_fields or [])
    if data.get("recipient_alias") or data.get("use_last_transfer") or data.get("recurring_hint"):
        missing.discard("recipient_alias")
    if data.get("amount"):
        missing.discard("amount")

    confidence = float(data.get("confidence") or 1.0)
    if ambiguous:
        confidence = min(confidence, 0.65)
    if missing:
        confidence = min(confidence, 0.75)

    data["ambiguous_fields"] = sorted(ambiguous)
    data["missing_fields"] = sorted(missing)
    data["evidence"] = evidence
    data["confidence"] = confidence
    return ExtractedSlots(**data)


def plan_with_llm(ctx: BankingContext, text: str, system_prompt: str) -> Optional[ExecutionPlan]:
    """Supervisor planning — LLM 구조화 출력. 실패 시 None (rule planner 폴백)."""
    llm = get_chat_model(ctx)
    if llm is None:
        return None
    try:
        structured = llm.with_structured_output(ExecutionPlan)
        with llm_call(ctx, "supervisor_planning", text) as awx_log:
            plan = structured.invoke([("system", system_prompt), ("user", text)])
            awx_log.output_message = plan.model_dump_json()
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
        with llm_call(ctx, "response_polish", draft) as awx_log:
            resp = llm.invoke([("system", system_prompt), ("user", draft)])
            _record_token_usage(awx_log, resp)
            awx_log.output_message = (resp.content or "").strip()
        out = (resp.content or "").strip()
        return out or draft
    except Exception:
        return draft


def _record_token_usage(awx_log, response) -> None:
    """Copy token counts from common LangChain/OpenAI response metadata shapes."""
    metadata = getattr(response, "response_metadata", None) or {}
    usage = metadata.get("token_usage") or metadata.get("usage") or {}
    input_tokens = usage.get("prompt_tokens") or usage.get("input_tokens")
    output_tokens = usage.get("completion_tokens") or usage.get("output_tokens")
    total_tokens = usage.get("total_tokens")
    if isinstance(input_tokens, int):
        awx_log.input_tokens = input_tokens
    if isinstance(output_tokens, int):
        awx_log.output_tokens = output_tokens
    if isinstance(total_tokens, int):
        awx_log.token_usage = total_tokens
