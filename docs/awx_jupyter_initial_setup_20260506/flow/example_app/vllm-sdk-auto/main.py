from __future__ import annotations

import argparse
import os
from typing import Any

from fastapi import FastAPI, HTTPException
from opentelemetry import trace
from pydantic import BaseModel, ConfigDict, Field

from awx.resources import Credential, ExternalResource

import telemetry
import vllm_runtime


DEFAULT_CREDENTIAL_SERVICE_ID = vllm_runtime.DEFAULT_CREDENTIAL_SERVICE_ID
DEFAULT_PROVIDER_ALIAS = vllm_runtime.DEFAULT_PROVIDER_ALIAS
DEFAULT_SERVICE_TYPE_NAME = vllm_runtime.DEFAULT_SERVICE_TYPE_NAME
DEFAULT_SOLUTION_ID = vllm_runtime.DEFAULT_SOLUTION_ID
DEFAULT_TEMPERATURE = vllm_runtime.DEFAULT_TEMPERATURE


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str = Field(..., min_length=1)
    model: str | None = None


def _extract_secret_value(credential_client: Credential, credential: Any) -> str | None:
    return vllm_runtime._extract_secret_value(credential_client, credential)


def _platform_code() -> str:
    return vllm_runtime._platform_code()


def _resolve_api_key() -> str:
    vllm_runtime.Credential = Credential
    vllm_runtime.HTTPException = HTTPException
    return vllm_runtime._resolve_api_key()


def _resolve_resource() -> dict[str, Any]:
    vllm_runtime.ExternalResource = ExternalResource
    vllm_runtime.HTTPException = HTTPException
    return vllm_runtime._resolve_resource()


def _resolve_base_url(resource: dict[str, Any]) -> str:
    vllm_runtime.HTTPException = HTTPException
    return vllm_runtime._resolve_base_url(resource)


def _resolve_model_name(resource: dict[str, Any], requested_model: str | None) -> str:
    vllm_runtime.HTTPException = HTTPException
    return vllm_runtime._resolve_model_name(resource, requested_model)


def _trace_id() -> str:
    telemetry.trace = trace
    return telemetry._trace_id()


async def _call_vllm(*, model: str, prompt: str, api_key: str, base_url: str) -> str:
    vllm_runtime.AsyncOpenAI = getattr(vllm_runtime, "AsyncOpenAI", None)
    vllm_runtime.HTTPException = HTTPException
    return await vllm_runtime._call_vllm(
        model=model,
        prompt=prompt,
        api_key=api_key,
        base_url=base_url,
    )


app = FastAPI(
    title="vLLM + AWX SDK Example",
    description="Minimal custom model(vLLM) example with AWX SDK and OTel export",
    version="0.1.0",
)


def _instrument_app() -> None:
    os.environ.setdefault("APP_NAME", "vllm-sdk-auto")
    try:
        from awx.observability.instrumentation.fastapi import instrument_app

        instrument_app(app)
    except Exception:
        pass


_instrument_app()


@app.get("/")
async def root() -> dict[str, str]:
    return {"app": "vllm-sdk-auto", "message": "Use POST /chat."}


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/chat")
async def chat(request: ChatRequest) -> dict[str, Any]:
    resource = _resolve_resource()
    model = _resolve_model_name(resource, request.model)
    base_url = _resolve_base_url(resource)
    api_key = _resolve_api_key()
    tracer = trace.get_tracer("vllm-sdk-auto")

    with tracer.start_as_current_span("vllm.chat") as span:
        if hasattr(span, "set_attribute"):
            span.set_attribute("gen_ai.system", "vllm")
            span.set_attribute("gen_ai.request.model", model)
            span.set_attribute("server.address", base_url)
            span.set_attribute("awx.provider.alias", DEFAULT_PROVIDER_ALIAS)
            span.set_attribute("awx.service.type", DEFAULT_SERVICE_TYPE_NAME)
        text = await _call_vllm(
            model=model,
            prompt=request.message,
            api_key=api_key,
            base_url=base_url,
        )

    return {
        "trace_id": _trace_id(),
        "model": model,
        "base_url": base_url,
        "response": text,
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
