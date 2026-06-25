"""Error normalization for banking integrations.

Real bank adapters will receive many different error codes from channel,
account, authentication, and transfer systems.  Agents should not branch on
vendor-specific strings, so this module maps those errors into safe categories.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


ErrorCategory = Literal[
    "validation",
    "authentication",
    "insufficient_balance",
    "limit_exceeded",
    "recipient_verification",
    "duplicate_request",
    "pending_result",
    "external_system",
    "unknown",
]


@dataclass(frozen=True)
class AgentSafeError:
    category: ErrorCategory
    message: str
    external_code: str = ""
    retryable: bool = False


class IntegrationError(Exception):
    """Exception raised inside adapters and converted at the service boundary."""

    def __init__(
        self,
        category: ErrorCategory,
        message: str,
        *,
        external_code: str = "",
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.safe_error = AgentSafeError(
            category=category,
            message=message,
            external_code=external_code,
            retryable=retryable,
        )


def map_external_code(code: str, default_message: str = "외부 시스템 처리 중 오류가 발생했습니다.") -> AgentSafeError:
    """Map a raw IBK/MCI/ESB style code into a stable agent category."""
    normalized = (code or "").upper()
    if normalized in {"BAL001", "INSUFFICIENT_BALANCE"}:
        return AgentSafeError("insufficient_balance", "잔액이 부족합니다.", code)
    if normalized in {"LIM001", "LIMIT_EXCEEDED"}:
        return AgentSafeError("limit_exceeded", "이체 한도를 초과했습니다.", code)
    if normalized in {"AUTH001", "OTP_FAIL", "AUTH_FAILED"}:
        return AgentSafeError("authentication", "인증에 실패했습니다.", code)
    if normalized in {"DUP001", "DUPLICATE"}:
        return AgentSafeError("duplicate_request", "이미 처리 중이거나 완료된 요청입니다.", code)
    if normalized in {"PENDING", "UNKNOWN_RESULT"}:
        return AgentSafeError("pending_result", "처리 결과 확인이 필요합니다.", code, retryable=True)
    return AgentSafeError("external_system", default_message, code, retryable=True)

