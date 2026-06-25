"""Small redaction helpers for AWX logs and telemetry payloads."""

from __future__ import annotations

import re
from typing import Any


_API_KEY_RE = re.compile(r"\b(sk-[A-Za-z0-9_-]{8,})\b")
_ASSIGNMENT_SECRET_RE = re.compile(
    r"\b((?:OPENAI_API_KEY|ANTHROPIC_API_KEY|API_KEY|TOKEN|SECRET)\s*=\s*)([^,\s]+)",
    re.IGNORECASE,
)
_BEARER_RE = re.compile(r"\b(Bearer\s+)([A-Za-z0-9._~+/=-]{12,})", re.IGNORECASE)
_PHONE_RE = re.compile(r"\b(01[016789])[-.\s]?(\d{3,4})[-.\s]?(\d{4})\b")
_ACCOUNT_RE = re.compile(r"\b(\d{2,6})-(\d{2,6})-(\d{4,10})(?:-(\d{1,6}))?\b")


def redact_text(value: Any) -> str:
    """Return a log-safe string while preserving enough shape for debugging."""
    if value is None:
        return ""
    text = str(value)
    text = _ASSIGNMENT_SECRET_RE.sub(r"\1***", text)
    text = _API_KEY_RE.sub("sk-***", text)
    text = _BEARER_RE.sub(r"\1***", text)
    text = _PHONE_RE.sub(lambda m: f"{m.group(1)}-****-{m.group(3)}", text)
    text = _ACCOUNT_RE.sub(_redact_account_match, text)
    return text


def _redact_account_match(match: re.Match[str]) -> str:
    raw = match.group(0)
    digits = re.sub(r"\D", "", raw)
    if len(digits) <= 4:
        return "****"
    return f"****-{digits[-4:]}"


def redact_mapping(payload: dict[str, Any]) -> dict[str, Any]:
    """Recursively redact a shallow telemetry mapping."""
    redacted: dict[str, Any] = {}
    for key, value in payload.items():
        lowered = key.lower()
        if any(marker in lowered for marker in ("key", "token", "secret", "password")):
            redacted[key] = "***" if value else value
        elif isinstance(value, dict):
            redacted[key] = redact_mapping(value)
        elif isinstance(value, list):
            redacted[key] = [
                redact_mapping(item) if isinstance(item, dict) else redact_text(item)
                for item in value
            ]
        elif isinstance(value, str):
            redacted[key] = redact_text(value)
        else:
            redacted[key] = value
    return redacted

