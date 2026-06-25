from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, TypedDict

from pydantic import BaseModel, Field


@dataclass
class QueuedChatMessage:
    message: str
    model: str | None = None
    attachments: list[str] = field(default_factory=list)


@dataclass
class ChatSessionState:
    session_id: str
    trace_carrier: dict[str, str] | None = None
    trace_id: str | None = None
    flow_run_id: str | None = None
    active_run_id: str | None = None
    active_task: asyncio.Task[Any] | None = None
    status: str = "idle"
    messages: list[dict[str, str]] = field(default_factory=list)
    prompt_messages: list[dict[str, str]] = field(default_factory=list)
    partial_response: str = ""
    pending_question: str | None = None
    pending_options: list[str] = field(default_factory=list)
    human_loop_count: int = 0
    active_phase: str = "idle"
    reasoning_summary: str = ""
    current_model: str | None = None
    steer_count: int = 0
    queued_messages: list[QueuedChatMessage] = field(default_factory=list)


class ChatSendRequest(BaseModel):
    message: str
    session_id: str | None = None
    model: str | None = None
    attachments: list[str] = Field(default_factory=list)
    force_steer: bool = False


class ChatTurnState(TypedDict, total=False):
    session_id: str
    run_id: str
    request_message: str
    api_key: str
    model: str
    next_action: str
    reasoning_summary: str
    question: str
    options: list[str]
    human_answer: str
    final_response: str
