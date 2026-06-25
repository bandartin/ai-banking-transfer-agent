from __future__ import annotations
import argparse
from contextlib import contextmanager
import os
from typing import Any, Iterator
from fastapi import FastAPI, HTTPException
from opentelemetry import trace
from pydantic import BaseModel, ConfigDict, Field
from awx.resources import Guardrail
try:
    from openai import AsyncOpenAI
except Exception:  # pragma: no cover
    AsyncOpenAI = None  # type: ignore[assignment]

DEFAULT_OPENAI_MODEL = "gpt-4o-mini"
DEFAULT_OPENAI_TEMPERATURE = 0.0
DEFAULT_FILTER_POLICY_IDS = [16]


class FilterLlmFilterRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    message: str = Field(..., min_length=1)
    model: str | None = None


class FilterLlmStreamFilterStreamRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    message: str = Field(..., min_length=1)
    chunk_size: int = Field(default=32, ge=1)
    overlap_tokens: int = Field(default=8, ge=0)
    holdback_tokens: int = Field(default=16, ge=0)
    model: str | None = None

def _model_name(model: str | None) -> str:
    return (model or os.getenv("OPENAI_MODEL") or DEFAULT_OPENAI_MODEL).strip()

def _configured_policy_ids() -> list[int]:
    raw_value = os.getenv("FILTER_POLICY_IDS")
    if raw_value is None:
        return list(DEFAULT_FILTER_POLICY_IDS)

    configured_ids: list[int] = []
    for raw_item in raw_value.split(","):
        value = raw_item.strip()
        if not value:
            continue
        try:
            policy_id = int(value)
        except ValueError as exc:
            raise ValueError("FILTER_POLICY_IDS must be a comma-separated list of integers") from exc
        if policy_id <= 0:
            raise ValueError("FILTER_POLICY_IDS must contain only positive integers")
        if policy_id not in configured_ids:
            configured_ids.append(policy_id)
    return configured_ids

def _trace_id() -> str:
    ctx = trace.get_current_span().get_span_context()
    return f"{ctx.trace_id:032x}" if ctx is not None and getattr(ctx, "is_valid", False) else ""

def _openai_client() -> Any:
    if AsyncOpenAI is None:
        raise HTTPException(status_code=500, detail={"code": "OPENAI_SDK_MISSING"})
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise HTTPException(status_code=400, detail={"code": "OPENAI_API_KEY_MISSING"})
    return AsyncOpenAI(api_key=api_key)

def _messages(prompt: str) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": "You are a concise Korean assistant. Answer in Korean and keep the reply short."},
        {"role": "user", "content": prompt},
    ]

def _text_from_completion(response: Any) -> str:
    choices = getattr(response, "choices", None) or []
    if not choices:
        return ""
    content = getattr(getattr(choices[0], "message", None), "content", "")
    return content if isinstance(content, str) else str(content or "")

def _delta_text(event: Any) -> str:
    if isinstance(event, dict):
        choices = event.get("choices") or []
        delta = (choices[0] if choices else {}).get("delta") or {}
        text = delta.get("content")
        return text if isinstance(text, str) else ""
    choices = getattr(event, "choices", None) or []
    delta = getattr(choices[0], "delta", None) if choices else None
    text = getattr(delta, "content", None) if delta is not None else None
    return text if isinstance(text, str) else ""

@contextmanager
def _llm_span(name: str, model: str) -> Iterator[Any | None]:
    try:
        tracer = trace.get_tracer("guardrail-sdk-auto")
        span_cm = tracer.start_as_current_span(name)
    except Exception:
        yield None
        return

    with span_cm as span:
        if hasattr(span, "set_attribute"):
            span.set_attribute("gen_ai.system", "openai")
            span.set_attribute("gen_ai.request.model", model)
        yield span

async def _call_llm_text(*, model: str, prompt: str) -> str:
    client = _openai_client()
    response = await client.chat.completions.create(
        model=model,
        temperature=DEFAULT_OPENAI_TEMPERATURE,
        messages=_messages(prompt),
    )
    return _text_from_completion(response)

async def _call_llm_stream_events(*, model: str, prompt: str) -> list[Any]:
    client = _openai_client()
    stream = await client.chat.completions.create(
        model=model,
        temperature=DEFAULT_OPENAI_TEMPERATURE,
        messages=_messages(prompt),
        stream=True,
    )
    events: list[Any] = []
    async for event in stream:
        events.append(event)
    return events

async def _run_filter_llm_filter(req: FilterLlmFilterRequest) -> dict[str, Any]:
    guardrail = Guardrail()
    model = _model_name(req.model)
    try:
        policy_ids = _configured_policy_ids()
    except ValueError as exc:
        raise HTTPException(
            status_code=500,
            detail={"code": "FILTER_POLICY_IDS_INVALID", "message": str(exc)},
        ) from exc
    filtered_in, input_status = guardrail.apply(
        input_text=req.message,
        policy_ids=policy_ids,
        mode="input",
    )
    with _llm_span("llm.invoke", model):
        llm_out = await _call_llm_text(model=model, prompt=filtered_in)
    filtered_out, output_status = guardrail.apply(
        input_text=llm_out,
        policy_ids=policy_ids,
        mode="output",
    )
    return {
        "trace_id": _trace_id(),
        "execution_mode": "non-stream",
        "policy_ids": policy_ids,
        "input_status": input_status,
        "output_status": output_status,
        "input_after_filter": filtered_in,
        "output_after_filter": filtered_out,
    }

async def _run_filter_llm_stream_filter_stream(req: FilterLlmStreamFilterStreamRequest) -> dict[str, Any]:
    guardrail = Guardrail()
    model = _model_name(req.model)
    try:
        policy_ids = _configured_policy_ids()
    except ValueError as exc:
        raise HTTPException(
            status_code=500,
            detail={"code": "FILTER_POLICY_IDS_INVALID", "message": str(exc)},
        ) from exc
    filtered_in, input_status = guardrail.apply(
        input_text=req.message,
        policy_ids=policy_ids,
        mode="input",
    )
    with _llm_span("llm.invoke.stream", model):
        events = await _call_llm_stream_events(model=model, prompt=filtered_in)
    filtered_out, output_status = guardrail.apply_openai_stream(
        events=events,
        policy_ids=policy_ids,
        mode="output",
        chunk_size=req.chunk_size,
        overlap_tokens=req.overlap_tokens,
        holdback_tokens=req.holdback_tokens,
    )
    return {
        "trace_id": _trace_id(),
        "execution_mode": "stream",
        "policy_ids": policy_ids,
        "input_status": input_status,
        "output_status": output_status,
        "stream_chunk_count": len(events),
        "llm_stream_text": "".join(_delta_text(event) for event in events),
        "output_after_filter": filtered_out,
    }

app = FastAPI(
    title="Filter SDK Only Example",
    description="Minimal app for filter->llm->filter and filter->llm(stream)->filter(stream)",
    version="0.4.1",
)

def _instrument_app() -> None:
    os.environ.setdefault("APP_NAME", "guardrail-sdk-auto")
    try:
        from awx.observability.instrumentation.fastapi import instrument_app
        instrument_app(app)
    except Exception:
        pass

_instrument_app()

@app.get("/")
async def root() -> dict[str, str]:
    return {"app": "guardrail-sdk-auto", "message": "Use /e2e/filter-llm-filter or /e2e/filter-llm-stream-filter-stream."}

@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}

@app.post("/e2e/filter-llm-filter")
async def e2e_filter_llm_filter(request: FilterLlmFilterRequest) -> dict[str, Any]:
    return await _run_filter_llm_filter(request)

@app.post("/e2e/filter-llm-stream-filter-stream")
async def e2e_filter_llm_stream_filter_stream(request: FilterLlmStreamFilterStreamRequest) -> dict[str, Any]:
    return await _run_filter_llm_stream_filter_stream(request)

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
