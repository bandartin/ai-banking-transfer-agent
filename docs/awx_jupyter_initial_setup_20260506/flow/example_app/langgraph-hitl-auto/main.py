from __future__ import annotations

import argparse
import os
from typing import Any

import uvicorn
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from opentelemetry import trace
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

from chat_files import attachment_context, available_models, render_prompt_message, render_user_message
from chat_models import ChatSendRequest
from chat_prompts import final_prompt_messages, parse_planner_output, planner_prompt_messages
from chat_runtime import ChatRuntime, openai_api_key_from_env
from chat_ui import (
    build_gradio_ui,
    gradio_chat_messages,
    gradio_choice_selector_update,
    gradio_css,
    gradio_timer_update,
)

STREAM_TOKEN_DELAY_SECONDS = 0.0
DEFAULT_OPENAI_MODEL = "gpt-4o-mini"
CHAT_INPUT_LINES = 1
DEFAULT_CHAT_MEMORY_TURNS = 3

TRACER = trace.get_tracer(__name__)
PROPAGATOR = TraceContextTextMapPropagator()


def _openai_model() -> str:
    return os.getenv("OPENAI_MODEL", DEFAULT_OPENAI_MODEL).strip() or DEFAULT_OPENAI_MODEL


def _resolve_model(explicit_model: str | None) -> str:
    if explicit_model and explicit_model.strip():
        return explicit_model.strip()
    return _openai_model()


def _chat_memory_turns() -> int:
    raw_value = os.getenv("CHAT_MEMORY_TURNS", str(DEFAULT_CHAT_MEMORY_TURNS)).strip()
    try:
        turns = int(raw_value)
    except ValueError:
        return DEFAULT_CHAT_MEMORY_TURNS
    return max(turns, 0)


runtime = ChatRuntime(
    tracer=TRACER,
    propagator=PROPAGATOR,
    stream_delay_getter=lambda: STREAM_TOKEN_DELAY_SECONDS,
    openai_api_key_getter=openai_api_key_from_env,
    openai_model_getter=_openai_model,
    resolve_model=_resolve_model,
    chat_memory_turns_getter=_chat_memory_turns,
    available_models_getter=lambda: available_models(_openai_model()),
    attachment_context=attachment_context,
    render_prompt_message=render_prompt_message,
    render_user_message=render_user_message,
    planner_prompt_messages=planner_prompt_messages,
    final_prompt_messages=final_prompt_messages,
    parse_planner_output=parse_planner_output,
)


def _new_session_id() -> str:
    return runtime.new_session_id()


def _gradio_chat_messages(payload: dict[str, Any]) -> list[dict[str, str]]:
    return gradio_chat_messages(payload)


def _gradio_timer_update(payload: dict[str, Any]) -> dict[str, Any]:
    return gradio_timer_update(payload)


def _build_gradio_ui() -> Any:
    return build_gradio_ui(
        new_session_id=_new_session_id,
        available_models=available_models(_openai_model()),
        chat_input_lines=CHAT_INPUT_LINES,
    )


app = FastAPI(title="LangGraph Human in the Loop with OTel")


def _instrument_app() -> None:
    try:
        from awx.observability.instrumentation.fastapi import instrument_app

        instrument_app(app)
    except Exception:
        pass


@app.post("/chat/send")
async def send_chat_message(request: ChatSendRequest) -> dict[str, Any]:
    return await runtime.send_chat_message(request)


@app.get("/chat/state/{session_id}")
async def get_chat_state(session_id: str) -> dict[str, Any]:
    return await runtime.get_chat_state(session_id)


@app.get("/")
async def root() -> dict[str, str]:
    return {"message": "LangGraph human-in-the-loop API with OpenTelemetry"}


def _mount_gradio_ui() -> None:
    global app
    try:
        import gradio as gr

        app = gr.mount_gradio_app(app, _build_gradio_ui(), path="/chat/ui", css=gradio_css())
    except Exception:
        @app.get("/chat/ui", response_class=HTMLResponse)
        async def chat_ui_unavailable() -> HTMLResponse:
            return HTMLResponse(
                "<html><body><h1>Gradio UI unavailable</h1><p>Install app dependencies with <code>uv sync</code> to enable /chat/ui.</p></body></html>",
                status_code=503,
            )


async def wait_for_all_chat_tasks() -> None:
    await runtime.wait_for_all_chat_tasks()


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the LangGraph HITL example")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8001)
    parser.add_argument("--root-path", default="")
    return parser.parse_args()


_instrument_app()
_mount_gradio_ui()


if __name__ == "__main__":
    args = _parse_args()
    uvicorn.run(app, host=args.host, port=args.port, root_path=args.root_path)
