"""FinancialCalculatorAgent — deterministic finance calculations.

RAG may explain formulas, but the numbers themselves are calculated in code.
That keeps financial math reproducible and testable, which is critical before
this agent is expanded to IBK product-specific calculation rules.
"""

from __future__ import annotations

import math
import re

from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime

from src.agents.context import BankingContext
from src.agents.state import BankingState
from src.agents.common import parsing
from src.agents.common.tracing import activity, traced


@traced("financial_calculator", "run")
def financial_calculator_node(state: dict, runtime: Runtime[BankingContext]) -> dict:
    message = state.get("current_message", "")
    if re.search(r"대출|원리금|상환", message):
        result = _loan_payment(message)
    else:
        result = _simple_deposit_interest(message)

    return {
        "agent_results": [{
            "agent": "financial_calculator",
            "kind": "calculation",
            "text": result["text"],
            "data": result["data"],
        }],
        "agent_activity": [activity("financial_calculator", "done", {"calculation_type": result["data"]["type"]})],
    }


def _simple_deposit_interest(message: str) -> dict:
    principal = parsing.parse_amount(message)
    annual_rate = _parse_rate(message)
    months = _parse_months(message)

    missing = []
    if principal is None:
        missing.append("금액")
    if annual_rate is None:
        missing.append("연 금리")
    if months is None:
        missing.append("기간")
    if missing:
        return {
            "text": f"계산에 필요한 정보가 부족합니다: {', '.join(missing)}. 예: 1,000만원을 연 3.5%로 12개월 예금하면?",
            "data": {"type": "deposit_interest", "missing_fields": missing},
        }

    gross_interest = int(principal * (annual_rate / 100) * (months / 12))
    tax = int(gross_interest * 0.154)
    net_interest = gross_interest - tax
    maturity_amount = principal + net_interest
    text = (
        "🧮 예금 이자 계산\n\n"
        f"원금: {principal:,}원\n"
        f"연 금리: {annual_rate:.3g}%\n"
        f"기간: {months}개월\n"
        f"세전 이자: {gross_interest:,}원\n"
        f"이자소득세(15.4% 가정): {tax:,}원\n"
        f"세후 예상 이자: {net_interest:,}원\n"
        f"만기 예상 금액: {maturity_amount:,}원\n\n"
        "실제 적용 금리와 세금은 상품 조건, 가입일, 우대금리 충족 여부에 따라 달라질 수 있습니다."
    )
    return {
        "text": text,
        "data": {
            "type": "deposit_interest",
            "principal": principal,
            "annual_rate": annual_rate,
            "months": months,
            "gross_interest": gross_interest,
            "tax": tax,
            "net_interest": net_interest,
            "maturity_amount": maturity_amount,
            "formula": "principal * annual_rate * months / 12",
        },
    }


def _loan_payment(message: str) -> dict:
    principal = parsing.parse_amount(message)
    annual_rate = _parse_rate(message)
    months = _parse_months(message)

    missing = []
    if principal is None:
        missing.append("대출금")
    if annual_rate is None:
        missing.append("연 금리")
    if months is None:
        missing.append("상환 기간")
    if missing:
        return {
            "text": f"대출 상환 계산에 필요한 정보가 부족합니다: {', '.join(missing)}. 예: 1억원을 연 4%로 30년 원리금균등 상환하면?",
            "data": {"type": "loan_payment", "missing_fields": missing},
        }

    monthly_rate = annual_rate / 100 / 12
    if monthly_rate == 0:
        monthly_payment = principal // months
    else:
        monthly_payment = int(principal * monthly_rate * math.pow(1 + monthly_rate, months) / (math.pow(1 + monthly_rate, months) - 1))
    total_payment = monthly_payment * months
    total_interest = total_payment - principal
    text = (
        "🧮 원리금균등 상환 계산\n\n"
        f"대출금: {principal:,}원\n"
        f"연 금리: {annual_rate:.3g}%\n"
        f"기간: {months}개월\n"
        f"예상 월 상환액: {monthly_payment:,}원\n"
        f"총 상환액: {total_payment:,}원\n"
        f"총 이자: {total_interest:,}원\n\n"
        "실제 상환액은 대출 실행일, 금리 변동, 중도상환, 부대비용에 따라 달라질 수 있습니다."
    )
    return {
        "text": text,
        "data": {
            "type": "loan_payment",
            "principal": principal,
            "annual_rate": annual_rate,
            "months": months,
            "monthly_payment": monthly_payment,
            "total_payment": total_payment,
            "total_interest": total_interest,
            "formula": "annuity_payment",
        },
    }


def _parse_rate(text: str) -> float | None:
    m = re.search(r"연\s*(\d+(?:\.\d+)?)\s*%", text)
    if not m:
        m = re.search(r"금리\s*(\d+(?:\.\d+)?)\s*%", text)
    if not m:
        m = re.search(r"(\d+(?:\.\d+)?)\s*%", text)
    return float(m.group(1)) if m else None


def _parse_months(text: str) -> int | None:
    m = re.search(r"(\d+)\s*년", text)
    if m:
        return int(m.group(1)) * 12
    m = re.search(r"(\d+)\s*개월", text)
    if m:
        return int(m.group(1))
    return None


def build_financial_calculator_subgraph():
    g = StateGraph(BankingState)
    g.add_node("run", financial_calculator_node)
    g.add_edge(START, "run")
    g.add_edge("run", END)
    return g.compile()

