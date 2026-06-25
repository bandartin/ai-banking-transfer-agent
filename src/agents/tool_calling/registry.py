"""Read-only tool registry for OpenAI function calling.

Phase 1 deliberately exposes only read/compute/RAG tools.  Transfer preparation,
validation, OTP, and execution stay in the existing TransferAgent workflow until
the policy gate for side-effecting tools is built.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from src.agents.context import BankingContext
from src.agents.common.services import recipient_service, security_rules
from src.agents.common.services.transfer_service import (
    build_transfer_summary,
    resolve_source_account,
    validate_transfer,
)


ToolHandler = Callable[["ToolRuntime", dict[str, Any]], "ToolResult"]


@dataclass(frozen=True)
class ToolRuntime:
    ctx: BankingContext
    state: dict[str, Any]


@dataclass(frozen=True)
class ToolResult:
    kind: str
    text: str
    data: dict[str, Any]
    source_agent: str
    memory: dict[str, Any] = field(default_factory=dict)

    def to_output(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "text": self.text,
            "data": self.data,
            "source_agent": self.source_agent,
        }


@dataclass(frozen=True)
class AgentTool:
    name: str
    description: str
    parameters: dict[str, Any]
    handler: ToolHandler
    side_effect: str = "read"

    def to_openai_schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters,
            "strict": True,
        }


_NO_ARGS = {
    "type": "object",
    "properties": {},
    "required": [],
    "additionalProperties": False,
}


def get_readonly_tools() -> list[AgentTool]:
    return [
        AgentTool(
            name="get_balance_summary",
            description=(
                "Return the signed-in banking user's account balances and daily "
                "transfer limits. Server context supplies the user id."
            ),
            parameters=_NO_ARGS,
            handler=lambda runtime, _args: _invoke_subagent(runtime, "inquiry", "balance"),
        ),
        AgentTool(
            name="get_transfer_history",
            description="Return the signed-in user's recent completed transfer history.",
            parameters=_NO_ARGS,
            handler=lambda runtime, _args: _invoke_subagent(runtime, "inquiry", "history"),
        ),
        AgentTool(
            name="get_recurring_transfers",
            description="Return the signed-in user's active recurring transfers.",
            parameters=_NO_ARGS,
            handler=lambda runtime, _args: _invoke_subagent(runtime, "inquiry", "recurring"),
        ),
        AgentTool(
            name="get_recipient_recommendations",
            description="Return recommended transfer recipients based on saved demo banking patterns.",
            parameters=_NO_ARGS,
            handler=lambda runtime, _args: _invoke_subagent(runtime, "recommend", "recipients"),
        ),
        AgentTool(
            name="search_menu_catalog",
            description=(
                "Search menu/screen-path knowledge. Use only for product menu, "
                "screen location, or app navigation questions, not customer values."
            ),
            parameters=_string_arg_schema("query", "User's menu or screen-path question."),
            handler=lambda runtime, args: _invoke_subagent(
                runtime, "menu_search", "menu", message=str(args.get("query") or runtime.state.get("current_message", ""))
            ),
        ),
        AgentTool(
            name="search_product_guide",
            description=(
                "Search product, fee, FAQ, and policy guide documents. Use for general "
                "banking guidance, not account-specific balances, limits, or transfer results."
            ),
            parameters=_string_arg_schema("query", "User's product, fee, FAQ, or policy question."),
            handler=lambda runtime, args: _invoke_subagent(
                runtime,
                "product_guide",
                "guide",
                message=str(args.get("query") or runtime.state.get("current_message", "")),
            ),
        ),
        AgentTool(
            name="calculate_finance",
            description=(
                "Run deterministic finance calculations such as deposit interest or "
                "loan amortization. The tool parses the question and returns reproducible math."
            ),
            parameters=_string_arg_schema("question", "Finance calculation question including amount, rate, and term."),
            handler=lambda runtime, args: _invoke_subagent(
                runtime,
                "financial_calculator",
                "calculate",
                message=str(args.get("question") or runtime.state.get("current_message", "")),
            ),
        ),
    ]


def get_transfer_prep_tools() -> list[AgentTool]:
    return [
        AgentTool(
            name="resolve_transfer_recipient",
            description=(
                "Resolve a recipient alias for transfer preparation. This does not "
                "prepare, validate, approve, or execute a transfer."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "recipient_alias": {"type": "string", "description": "Recipient name or alias from the user."},
                    "bank_hint": {
                        "type": ["string", "null"],
                        "description": "Optional destination bank hint, or null.",
                    },
                },
                "required": ["recipient_alias", "bank_hint"],
                "additionalProperties": False,
            },
            handler=_resolve_transfer_recipient,
            side_effect="prepare",
        ),
        AgentTool(
            name="prepare_transfer_summary",
            description=(
                "Build and pre-validate a transfer summary for human confirmation. "
                "This tool never executes money movement."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "recipient_id": {"type": "integer", "description": "Recipient id returned by resolve_transfer_recipient."},
                    "favorite_id": {"type": ["integer", "null"], "description": "Favorite id if known, or null."},
                    "recipient_alias": {"type": ["string", "null"], "description": "Alias to show on the confirmation card."},
                    "amount": {"type": "integer", "minimum": 1, "description": "Transfer amount in KRW."},
                    "memo": {"type": ["string", "null"], "description": "Optional transfer memo, or null."},
                    "source_account_hint": {
                        "type": ["string", "null"],
                        "description": "Optional source account hint, or null.",
                    },
                },
                "required": [
                    "recipient_id",
                    "favorite_id",
                    "recipient_alias",
                    "amount",
                    "memo",
                    "source_account_hint",
                ],
                "additionalProperties": False,
            },
            handler=_prepare_transfer_summary,
            side_effect="prepare",
        ),
    ]


def get_tools(*, allow_transfer_prep: bool = False) -> list[AgentTool]:
    tools = list(get_readonly_tools())
    if allow_transfer_prep:
        tools.extend(get_transfer_prep_tools())
    return tools


def get_tool_map() -> dict[str, AgentTool]:
    return {tool.name: tool for tool in get_tools(allow_transfer_prep=True)}


def get_tool_map_for_mode(*, allow_transfer_prep: bool = False) -> dict[str, AgentTool]:
    return {tool.name: tool for tool in get_tools(allow_transfer_prep=allow_transfer_prep)}


def _string_arg_schema(name: str, description: str) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            name: {"type": "string", "description": description},
        },
        "required": [name],
        "additionalProperties": False,
    }


def _invoke_subagent(
    runtime: ToolRuntime,
    agent: str,
    sub_intent: str,
    *,
    message: str | None = None,
) -> ToolResult:
    graph = _build_subgraph(agent)
    state = {
        "user_id": runtime.ctx.user_id,
        "session_id": runtime.ctx.session_id,
        "current_message": message if message is not None else runtime.state.get("current_message", ""),
        "sub_intent": sub_intent,
        "last_recommendations": runtime.state.get("last_recommendations", []),
        "last_history_items": runtime.state.get("last_history_items", []),
        "last_balance_summary": runtime.state.get("last_balance_summary"),
        "last_followup_source": runtime.state.get("last_followup_source", ""),
    }
    out = graph.invoke(state, context=runtime.ctx)
    results = out.get("agent_results") or []
    first = results[0] if results else {}
    memory = {
        key: out[key]
        for key in (
            "last_recommendations",
            "last_history_items",
            "last_balance_summary",
            "last_followup_source",
        )
        if key in out
    }
    return ToolResult(
        kind=str(first.get("kind") or sub_intent or "message"),
        text=str(first.get("text") or ""),
        data=first.get("data") or {},
        source_agent=str(first.get("agent") or agent),
        memory=memory,
    )


def _build_subgraph(agent: str):
    if agent == "inquiry":
        from src.agents.subagents.inquiry import build_inquiry_subgraph

        return build_inquiry_subgraph()
    if agent == "recommend":
        from src.agents.subagents.recommend import build_recommend_subgraph

        return build_recommend_subgraph()
    if agent == "menu_search":
        from src.agents.subagents.menu_search import build_menu_search_subgraph

        return build_menu_search_subgraph()
    if agent == "product_guide":
        from src.agents.subagents.product_guide import build_product_guide_subgraph

        return build_product_guide_subgraph()
    if agent == "financial_calculator":
        from src.agents.subagents.financial_calculator import build_financial_calculator_subgraph

        return build_financial_calculator_subgraph()
    raise KeyError(f"Unsupported read-only tool agent: {agent}")


def _resolve_transfer_recipient(runtime: ToolRuntime, args: dict[str, Any]) -> ToolResult:
    alias = str(args.get("recipient_alias") or "").strip()
    bank_hint = str(args.get("bank_hint") or "").strip()
    if not alias:
        suggestions = recipient_service.get_top_recipients(runtime.ctx.user_id, limit=5)
        return _recipient_result("recipient_missing", "수신자 이름이나 별칭이 필요합니다.", suggestions)

    matches = recipient_service.find_by_alias(runtime.ctx.user_id, alias)
    if bank_hint:
        matches = [
            item for item in matches
            if bank_hint.replace(" ", "") in str(item.get("bank_name") or "").replace(" ", "")
        ]

    if len(matches) == 1:
        item = matches[0]
        data = {
            "status": "resolved",
            "recipient_id": item.get("recipient_id"),
            "favorite_id": item.get("favorite_id"),
            "alias": item.get("alias") or alias,
            "name": item.get("name"),
            "bank_name": item.get("bank_name"),
            "account_masked": _mask_account(str(item.get("account_number") or "")),
            "execution_allowed": False,
        }
        return ToolResult(
            kind="transfer_recipient",
            text=f"{data['name']}님({data['bank_name']})으로 수신자를 확인했습니다.",
            data=data,
            source_agent="tool_agent",
        )

    if len(matches) > 1:
        return _recipient_result(
            "ambiguous",
            "같은 별칭에 해당하는 수신자가 여러 명입니다. 사용자 확인이 필요합니다.",
            matches,
        )

    suggestions = recipient_service.get_top_recipients(runtime.ctx.user_id, limit=5)
    return _recipient_result(
        "not_found",
        "해당 별칭의 등록 수신자를 찾지 못했습니다. 사용자 확인이 필요합니다.",
        suggestions,
    )


def _prepare_transfer_summary(runtime: ToolRuntime, args: dict[str, Any]) -> ToolResult:
    from src.models.database import Recipient, db

    recipient_id = args.get("recipient_id")
    amount = int(args.get("amount") or 0)
    recipient = db.session.get(Recipient, recipient_id) if recipient_id else None
    if recipient is None or amount <= 0:
        return ToolResult(
            kind="transfer_prep",
            text="이체 준비에 필요한 수신자 또는 금액 정보가 부족합니다.",
            data={"status": "invalid_arguments", "execution_allowed": False},
            source_agent="tool_agent",
        )

    source_account_id = None
    source_hint = args.get("source_account_hint")
    source_error = None
    if source_hint:
        source_account_id, source_error = resolve_source_account(runtime.ctx.user_id, str(source_hint))
        if source_error:
            return ToolResult(
                kind="transfer_prep",
                text=source_error,
                data={"status": "source_account_not_found", "execution_allowed": False},
                source_agent="tool_agent",
            )

    summary = build_transfer_summary(
        runtime.ctx,
        runtime.ctx.user_id,
        {
            "name": recipient.name,
            "bank_name": recipient.bank_name,
            "account_number": recipient.account_number,
            "alias": args.get("recipient_alias"),
        },
        amount,
        args.get("memo"),
        source_account_id=source_account_id,
    )
    if summary is None:
        return ToolResult(
            kind="transfer_prep",
            text="출금 계좌를 찾지 못해 이체 준비를 중단했습니다.",
            data={"status": "source_account_missing", "execution_allowed": False},
            source_agent="tool_agent",
        )

    validation = validate_transfer(runtime.ctx.user_id, summary)
    risk = security_rules.assess_transfer(runtime.ctx, runtime.ctx.user_id, summary)
    summary_data = summary.model_dump()
    summary_data["requires_otp"] = summary.requires_otp or risk.force_otp
    summary_data["warnings"] = list(validation.warnings) + list(risk.warnings)

    status = "ready_for_confirmation" if validation.passed else "validation_failed"
    text = _transfer_prep_text(status, summary_data, validation.errors, risk.level)
    return ToolResult(
        kind="transfer_prep",
        text=text,
        data={
            "status": status,
            "summary": summary_data,
            "validation": validation.model_dump(),
            "risk_assessment": risk.model_dump(),
            "recipient_id": recipient_id,
            "favorite_id": args.get("favorite_id"),
            "execution_allowed": False,
            "requires_human_confirmation": validation.passed,
        },
        source_agent="tool_agent",
    )


def _recipient_result(status: str, text: str, items: list[dict[str, Any]]) -> ToolResult:
    candidates = []
    for idx, item in enumerate(items, start=1):
        candidates.append(
            {
                "index": idx,
                "recipient_id": item.get("recipient_id"),
                "favorite_id": item.get("favorite_id"),
                "alias": item.get("alias"),
                "name": item.get("name"),
                "bank_name": item.get("bank_name"),
                "account_masked": _mask_account(str(item.get("account_number") or "")),
            }
        )
    return ToolResult(
        kind="transfer_recipient",
        text=text,
        data={"status": status, "candidates": candidates, "execution_allowed": False},
        source_agent="tool_agent",
    )


def _transfer_prep_text(status: str, summary: dict[str, Any], errors: list[str], risk_level: str) -> str:
    if status == "validation_failed":
        return "이체 사전 검증에 실패했습니다.\n" + "\n".join(f"- {error}" for error in errors)
    return (
        "이체 정보를 준비했습니다. 아직 이체는 실행되지 않았습니다.\n"
        f"- 받는 분: {summary['recipient_name']} ({summary['recipient_bank']})\n"
        f"- 금액: {summary['amount']:,}원\n"
        f"- 수수료: {summary['fee']:,}원\n"
        f"- 총 출금액: {summary['total_deducted']:,}원\n"
        f"- OTP 필요: {'예' if summary['requires_otp'] else '아니오'}\n"
        f"- 리스크 등급: {risk_level}\n"
        "사용자 확인 단계로 넘기기 전까지 실행 권한은 없습니다."
    )


def _mask_account(account_number: str) -> str:
    if len(account_number) <= 4:
        return account_number
    return f"{account_number[:3]}***{account_number[-4:]}"
