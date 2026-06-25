from __future__ import annotations

import argparse
import os
from typing import Any

from fastapi import FastAPI, HTTPException
from opentelemetry import trace
from pydantic import BaseModel, ConfigDict, Field

from awx.resources import Credential

try:
    from openai import AsyncOpenAI
except Exception:  # pragma: no cover
    AsyncOpenAI = None  # type: ignore[assignment]


DEFAULT_SERVICE_ID = 30
DEFAULT_PROVIDER_ALIAS = "OpenAI"
DEFAULT_SERVICE_TYPE_NAME = "LLM"
DEFAULT_OPENAI_MODEL = "gpt-4o-mini"
DEFAULT_OPENAI_TEMPERATURE = 0.0


class CredentialSummaryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    service_id: int = Field(default=DEFAULT_SERVICE_ID, ge=1)
    provider_alias: str = Field(default=DEFAULT_PROVIDER_ALIAS, min_length=1)
    service_type_name: str = Field(default=DEFAULT_SERVICE_TYPE_NAME, min_length=1)
    tag: str | None = None


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str = Field(..., min_length=1)
    model: str | None = None
    service_id: int = Field(default=DEFAULT_SERVICE_ID, ge=1)
    provider_alias: str = Field(default=DEFAULT_PROVIDER_ALIAS, min_length=1)
    service_type_name: str = Field(default=DEFAULT_SERVICE_TYPE_NAME, min_length=1)
    tag: str | None = None


def _trace_id() -> str:
    ctx = trace.get_current_span().get_span_context()
    return f"{ctx.trace_id:032x}" if ctx is not None and getattr(ctx, "is_valid", False) else ""


def _instrument_app() -> None:
    os.environ.setdefault("APP_NAME", "fastapi-credential-sdk-auto")
    try:
        from awx.observability.instrumentation.fastapi import instrument_app

        instrument_app(app)
    except Exception:
        pass


def _variable_names(credential: dict[str, Any]) -> list[str]:
    names: list[str] = []
    for item in credential.get("variables", []):
        if not isinstance(item, dict):
            continue
        raw = item.get("attributeName") or item.get("name")
        if isinstance(raw, str) and raw.strip():
            names.append(raw.strip())
    return names


def _credential_variable_value(
    credential: dict[str, Any],
    *candidate_names: str,
) -> str | None:
    normalized_candidates = {name.strip().lower() for name in candidate_names if name.strip()}
    for item in credential.get("variables", []):
        if not isinstance(item, dict):
            continue
        raw_name = item.get("attributeName") or item.get("name")
        if not isinstance(raw_name, str) or raw_name.strip().lower() not in normalized_candidates:
            continue
        raw_value = item.get("attributeValue") or item.get("value")
        if isinstance(raw_value, str) and raw_value.strip():
            return raw_value.strip()
    return None


def _resolved_model_name(model: str | None) -> str:
    return (model or os.getenv("OPENAI_MODEL") or DEFAULT_OPENAI_MODEL).strip()


def _messages(prompt: str) -> list[dict[str, str]]:
    return [
        {
            "role": "system",
            "content": "You are a concise Korean assistant. Answer in Korean and keep the reply short.",
        },
        {"role": "user", "content": prompt},
    ]


def _text_from_completion(response: Any) -> str:
    choices = getattr(response, "choices", None) or []
    if not choices:
        return ""
    content = getattr(getattr(choices[0], "message", None), "content", "")
    return content if isinstance(content, str) else str(content or "")


def _openai_client(*, api_key: str, base_url: str | None = None) -> Any:
    if AsyncOpenAI is None:
        raise HTTPException(
            status_code=500,
            detail={
                "code": "OPENAI_SDK_MISSING",
                "message": "The openai package is required for /chat.",
            },
        )
    return AsyncOpenAI(api_key=api_key, base_url=base_url)


app = FastAPI(
    title="FastAPI Credential SDK Example",
    description="Minimal FastAPI example that resolves AWX credentials and performs an LLM chat call.",
    version="0.1.0",
)

_instrument_app()


@app.get("/")
async def root() -> dict[str, str]:
    return {
        "app": "fastapi-credential-sdk-auto",
        "message": "Use POST /credential/summary or POST /chat.",
    }


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "fastapi-credential-sdk-auto"}


@app.post("/credential/summary")
async def credential_summary(request: CredentialSummaryRequest) -> dict[str, Any]:
    credential_client = Credential()
    credentials = credential_client.get(
        service_id=request.service_id,
        provider_alias=request.provider_alias,
        service_type_name=request.service_type_name,
        tag=request.tag,
    )
    if not credentials:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "CREDENTIAL_NOT_FOUND",
                "message": "No credential was returned for the given request.",
            },
        )

    selected = credentials[0]
    secret = Credential.extract_secret_value(selected)

    return {
        "trace_id": _trace_id(),
        "service_id": request.service_id,
        "provider_alias": request.provider_alias,
        "service_type_name": request.service_type_name,
        "credential_count": len(credentials),
        "selected_credential_id": str(selected.get("credentialId") or selected.get("credential_id") or ""),
        "selected_tag": selected.get("tag"),
        "variable_names": _variable_names(selected),
        "secret_resolved": bool(secret),
    }


@app.post("/chat")
async def chat(request: ChatRequest) -> dict[str, Any]:
    credential_client = Credential()
    credentials = credential_client.get(
        service_id=request.service_id,
        provider_alias=request.provider_alias,
        service_type_name=request.service_type_name,
        tag=request.tag,
    )
    if not credentials:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "CREDENTIAL_NOT_FOUND",
                "message": "No credential was returned for the given request.",
            },
        )

    selected = credentials[0]
    secret = Credential.extract_secret_value(selected)
    if not secret:
        raise HTTPException(
            status_code=500,
            detail={
                "code": "CREDENTIAL_SECRET_MISSING",
                "message": "Credential was found but no secret value could be resolved.",
            },
        )

    base_url = _credential_variable_value(selected, "BASE_URL", "OPENAI_BASE_URL")
    model = _resolved_model_name(request.model)
    client = _openai_client(api_key=secret, base_url=base_url)
    response = await client.chat.completions.create(
        model=model,
        temperature=DEFAULT_OPENAI_TEMPERATURE,
        messages=_messages(request.message),
    )

    return {
        "trace_id": _trace_id(),
        "assistant_message": _text_from_completion(response),
        "model": model,
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default=os.getenv("HOST", "0.0.0.0"))
    parser.add_argument("--port", type=int, default=int(os.getenv("PORT", "8000")))
    parser.add_argument("--root-path", default=os.getenv("ROOT_PATH", ""))
    return parser.parse_args()


if __name__ == "__main__":
    import uvicorn

    args = _parse_args()
    uvicorn.run(app, host=args.host, port=args.port, root_path=args.root_path)
