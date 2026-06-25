from __future__ import annotations

import asyncio
from contextlib import suppress
from typing import Any, Callable
from uuid import uuid4

from fastapi import HTTPException
from opentelemetry import trace
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from chat_models import ChatSendRequest, ChatSessionState, ChatTurnState, QueuedChatMessage


class ChatRuntime:
    def __init__(
        self,
        *,
        tracer: Any,
        propagator: Any,
        stream_delay_getter: Callable[[], float],
        openai_api_key_getter: Callable[[], str],
        openai_model_getter: Callable[[], str],
        resolve_model: Callable[[str | None], str],
        chat_memory_turns_getter: Callable[[], int],
        available_models_getter: Callable[[], list[str]],
        attachment_context: Callable[[list[str]], tuple[list[str], str]],
        render_prompt_message: Callable[[str, str], str],
        render_user_message: Callable[[str, list[str]], str],
        planner_prompt_messages: Callable[[list[dict[str, str]]], list[dict[str, str]]],
        final_prompt_messages: Callable[[list[dict[str, str]]], list[dict[str, str]]],
        parse_planner_output: Callable[[str], tuple[str, str, str, list[str]]],
    ) -> None:
        self.tracer = tracer
        self.propagator = propagator
        self.stream_delay_getter = stream_delay_getter
        self.openai_api_key_getter = openai_api_key_getter
        self.openai_model_getter = openai_model_getter
        self.resolve_model = resolve_model
        self.chat_memory_turns_getter = chat_memory_turns_getter
        self.available_models_getter = available_models_getter
        self.attachment_context = attachment_context
        self.render_prompt_message = render_prompt_message
        self.render_user_message = render_user_message
        self.planner_prompt_messages = planner_prompt_messages
        self.final_prompt_messages = final_prompt_messages
        self.parse_planner_output = parse_planner_output
        self.chat_sessions: dict[str, ChatSessionState] = {}
        self.chat_session_locks: dict[str, asyncio.Lock] = {}
        self.chat_graph = self._build_graph()

    def _build_graph(self) -> Any:
        workflow = StateGraph(ChatTurnState)
        workflow.add_node("plan_next_step", self._plan_next_step_node)
        workflow.add_node("await_human_input", self._await_human_input_node)
        workflow.add_node("final_answer", self._final_answer_node)
        workflow.add_edge(START, "plan_next_step")
        workflow.add_conditional_edges("plan_next_step", self._route_after_planning)
        workflow.add_edge("await_human_input", "plan_next_step")
        workflow.add_edge("final_answer", END)
        return workflow.compile(checkpointer=MemorySaver())

    def new_session_id(self) -> str:
        return str(uuid4())

    def get_chat_session(self, session_id: str) -> ChatSessionState:
        return self.chat_sessions.setdefault(session_id, ChatSessionState(session_id=session_id))

    def get_chat_session_lock(self, session_id: str) -> asyncio.Lock:
        return self.chat_session_locks.setdefault(session_id, asyncio.Lock())

    def _openai_client(self, api_key: str) -> Any:
        from openai import AsyncOpenAI

        return AsyncOpenAI(api_key=api_key)

    def _chunk_text(self, chunk: Any) -> str:
        choices = getattr(chunk, "choices", None) or []
        if not choices:
            return ""
        delta = getattr(choices[0], "delta", None)
        if delta is None:
            return ""
        content = getattr(delta, "content", "")
        return content or ""

    def trace_id_hex(self) -> str:
        span_context = trace.get_current_span().get_span_context()
        if not span_context.is_valid:
            return "0" * 32
        return f"{span_context.trace_id:032x}"

    def extract_context_from_carrier(self, carrier: dict[str, str] | None) -> Any:
        if not carrier:
            return None
        return self.propagator.extract(carrier)

    async def stream_openai_response(
        self,
        *,
        session: ChatSessionState,
        run_id: str,
        api_key: str,
        model: str,
        messages: list[dict[str, str]],
    ) -> str:
        stream = await self._openai_client(api_key).chat.completions.create(
            model=model,
            messages=messages,
            stream=True,
        )
        chunks: list[str] = []
        try:
            async for chunk in stream:
                if session.active_run_id != run_id:
                    raise asyncio.CancelledError()
                token = self._chunk_text(chunk)
                if not token:
                    continue
                chunks.append(token)
                session.partial_response = "".join(chunks).strip()
                if self.stream_delay_getter() > 0:
                    await asyncio.sleep(self.stream_delay_getter())
        finally:
            close_stream = getattr(stream, "aclose", None)
            if callable(close_stream):
                await close_stream()
        return "".join(chunks).strip()

    def history_window(self, session: ChatSessionState) -> list[dict[str, str]]:
        history = [
            {"role": item["role"], "content": item["content"]}
            for item in session.prompt_messages
            if item.get("role") in {"user", "assistant"}
        ]
        window = self.chat_memory_turns_getter() * 2
        if window > 0:
            return history[-window:]
        return []

    def _plan_next_step_node(self, state: ChatTurnState) -> ChatTurnState:
        session = self.get_chat_session(state["session_id"])
        raw_plan = asyncio.run(
            self.stream_openai_response(
                session=session,
                run_id=state["run_id"],
                api_key=state["api_key"],
                model=state["model"],
                messages=self.planner_prompt_messages(self.history_window(session)),
            )
        )
        next_action, reasoning_summary, question, options = self.parse_planner_output(raw_plan)
        return {
            "next_action": next_action,
            "reasoning_summary": reasoning_summary,
            "question": question,
            "options": options,
        }

    def _await_human_input_node(self, state: ChatTurnState) -> ChatTurnState:
        human_answer = interrupt(
            {
                "question": state.get("question", ""),
                "options": state.get("options", []),
            }
        )
        return {"human_answer": human_answer}

    def _final_answer_node(self, state: ChatTurnState) -> ChatTurnState:
        session = self.get_chat_session(state["session_id"])
        session.partial_response = ""
        session.active_phase = "final_answer"
        final_response = asyncio.run(
            self.stream_openai_response(
                session=session,
                run_id=state["run_id"],
                api_key=state["api_key"],
                model=state["model"],
                messages=self.final_prompt_messages(self.history_window(session)),
            )
        )
        return {"final_response": final_response}

    def _route_after_planning(self, state: ChatTurnState) -> str:
        if state.get("next_action") == "ask":
            return "await_human_input"
        return "final_answer"

    def chat_state_payload(self, session: ChatSessionState) -> dict[str, Any]:
        active_run = None
        if session.active_task is not None and not session.active_task.done():
            active_run = session.active_run_id
        return {
            "session_id": session.session_id,
            "trace_id": session.trace_id,
            "status": session.status,
            "active_run": active_run,
            "messages": list(session.messages),
            "partial_response": session.partial_response,
            "pending_question": session.pending_question,
            "pending_options": list(session.pending_options),
            "human_loop_count": session.human_loop_count,
            "active_phase": session.active_phase,
            "reasoning_summary": session.reasoning_summary,
            "model": session.current_model or self.openai_model_getter(),
            "available_models": self.available_models_getter(),
            "steer_count": session.steer_count,
            "queue_count": len(session.queued_messages),
            "can_steer": bool(active_run and session.active_phase == "final_answer"),
        }

    def empty_chat_state_payload(self, session_id: str) -> dict[str, Any]:
        return {
            "session_id": session_id,
            "trace_id": "",
            "status": "idle",
            "active_run": None,
            "messages": [],
            "partial_response": "",
            "pending_question": None,
            "pending_options": [],
            "human_loop_count": 0,
            "active_phase": "idle",
            "reasoning_summary": "",
            "model": self.openai_model_getter(),
            "available_models": self.available_models_getter(),
            "steer_count": 0,
            "queue_count": 0,
            "can_steer": False,
        }

    async def run_chat_turn(
        self,
        session_id: str,
        run_id: str,
        carrier: dict[str, str] | None,
        api_key: str,
        model: str,
        request_message: str | None = None,
        human_answer: str | None = None,
    ) -> None:
        session = self.get_chat_session(session_id)
        parent_context = self.extract_context_from_carrier(carrier)
        current_task = asyncio.current_task()
        try:
            with self.tracer.start_as_current_span(
                "langgraph.chat.turn",
                context=parent_context,
            ) as span:
                span.set_attribute("awx.session.id", session_id)
                span.set_attribute("langgraph.session_id", session_id)
                span.set_attribute("langgraph.run_id", run_id)
                span.set_attribute("langgraph.chat.phase", "turn")
                span.set_attribute("gen_ai.system", "openai")
                span.set_attribute("gen_ai.request.model", model)
                session.current_model = model
                graph_config = {"configurable": {"thread_id": session_id}}
                if human_answer is None:
                    result = await asyncio.to_thread(
                        self.chat_graph.invoke,
                        {
                            "session_id": session_id,
                            "run_id": run_id,
                            "request_message": request_message or "",
                            "api_key": api_key,
                            "model": model,
                        },
                        graph_config,
                    )
                else:
                    result = await asyncio.to_thread(
                        self.chat_graph.invoke,
                        Command(resume=human_answer),
                        graph_config,
                    )

                if session.flow_run_id != run_id:
                    return

                interrupts = result.get("__interrupt__") or []
                if interrupts:
                    payload = interrupts[0].value if interrupts else {}
                    question = str(payload.get("question") or result.get("question") or "").strip()
                    options = payload.get("options") or result.get("options") or []
                    session.reasoning_summary = str(result.get("reasoning_summary") or "").strip()
                    if question:
                        session.messages.append({"role": "assistant", "content": question})
                        session.prompt_messages.append({"role": "assistant", "content": question})
                    session.pending_question = question
                    session.pending_options = [str(item).strip() for item in options if str(item).strip()]
                    session.human_loop_count += 1
                    session.partial_response = ""
                    session.status = "awaiting_human"
                    session.active_phase = "awaiting_human"
                    session.trace_id = self.trace_id_hex()
                    updated_carrier: dict[str, str] = {}
                    self.propagator.inject(updated_carrier)
                    session.trace_carrier = updated_carrier
                    span.set_attribute("langgraph.hitl.awaiting_human", True)
                    return

                response = result.get("final_response", "").strip()
                if response:
                    session.messages.append({"role": "assistant", "content": response})
                    session.prompt_messages.append({"role": "assistant", "content": response})
                session.partial_response = ""
                session.status = "completed"
                session.active_phase = "idle"
                session.pending_question = None
                session.pending_options = []
                session.reasoning_summary = str(result.get("reasoning_summary") or session.reasoning_summary).strip()
                session.trace_id = self.trace_id_hex()
                span.set_attribute("langgraph.hitl.awaiting_human", False)
        except asyncio.CancelledError:
            raise
        finally:
            should_dispatch_queued = False
            if session.active_task is current_task:
                session.active_task = None
                if session.active_run_id == run_id:
                    session.active_run_id = None
                if session.status != "awaiting_human" and session.flow_run_id == run_id:
                    session.flow_run_id = None
                    session.trace_carrier = None
                    session.active_phase = "idle"
                should_dispatch_queued = session.active_task is None and bool(session.queued_messages)
            if should_dispatch_queued:
                asyncio.create_task(self.dispatch_next_queued_message(session_id))

    async def wait_for_all_chat_tasks(self) -> None:
        tasks = [
            session.active_task
            for session in self.chat_sessions.values()
            if session.active_task is not None
        ]
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def dispatch_next_queued_message(self, session_id: str) -> None:
        await asyncio.sleep(0)
        async with self.get_chat_session_lock(session_id):
            session = self.chat_sessions.get(session_id)
            if session is None or session.active_task is not None or not session.queued_messages:
                return
            queued = session.queued_messages.pop(0)
        await self.send_chat_message(
            ChatSendRequest(
                session_id=session_id,
                message=queued.message,
                model=queued.model,
                attachments=list(queued.attachments),
            )
        )

    async def interrupt_for_steer(self, session: ChatSessionState) -> bool:
        active_task = session.active_task
        if active_task is None or active_task.done():
            return False
        if session.active_phase != "final_answer":
            return False

        interrupted_run_id = session.active_run_id
        partial_response = session.partial_response.strip()
        session.flow_run_id = None
        session.trace_carrier = None
        session.active_run_id = None
        active_task.cancel()
        with suppress(asyncio.CancelledError):
            await active_task
        if partial_response:
            session.messages.append({"role": "assistant", "content": partial_response})
            session.prompt_messages.append({"role": "assistant", "content": partial_response})
        session.partial_response = ""
        session.pending_question = None
        session.pending_options = []
        session.status = "idle"
        session.active_phase = "idle"
        session.reasoning_summary = ""
        session.steer_count += 1
        return bool(interrupted_run_id)

    async def send_chat_message(self, request: ChatSendRequest) -> dict[str, Any]:
        session_id = request.session_id or str(uuid4())
        session = self.get_chat_session(session_id)
        api_key = self.openai_api_key_getter()
        model = self.resolve_model(request.model)
        attachment_names, attachment_blob = self.attachment_context(request.attachments)
        prompt_message = self.render_prompt_message(request.message, attachment_blob)
        display_message = self.render_user_message(request.message, attachment_names)
        async with self.get_chat_session_lock(session_id):
            previous_task = session.active_task
            if previous_task is not None and not previous_task.done():
                if request.force_steer:
                    steered = await self.interrupt_for_steer(session)
                    if not steered:
                        session.queued_messages.append(
                            QueuedChatMessage(
                                message=request.message,
                                model=request.model,
                                attachments=list(request.attachments),
                            )
                        )
                        return {
                            "status": "queued",
                            "session_id": session_id,
                            "trace_id": session.trace_id or "",
                            "model": model,
                            "queue_length": len(session.queued_messages),
                            "otel": {"same_trace": False},
                        }
                else:
                    session.queued_messages.append(
                        QueuedChatMessage(
                            message=request.message,
                            model=request.model,
                            attachments=list(request.attachments),
                        )
                    )
                    return {
                        "status": "queued",
                        "session_id": session_id,
                        "trace_id": session.trace_id or "",
                        "model": model,
                        "queue_length": len(session.queued_messages),
                        "otel": {"same_trace": False},
                    }

            is_resume = session.status == "awaiting_human" and session.pending_question is not None
            base_context = self.extract_context_from_carrier(session.trace_carrier) if is_resume else None
            with self.tracer.start_as_current_span(
                "langgraph.chat.send",
                context=base_context,
            ) as span:
                span.set_attribute("awx.session.id", session_id)
                span.set_attribute("langgraph.session_id", session_id)
                span.set_attribute("langgraph.chat.phase", "send")
                span.set_attribute("gen_ai.system", "openai")
                span.set_attribute("gen_ai.request.model", model)
                span.set_attribute("langgraph.chat.memory_turns", self.chat_memory_turns_getter())
                carrier: dict[str, str] = {}
                self.propagator.inject(carrier)
                trace_id = self.trace_id_hex()
                session.trace_id = trace_id
                run_id = session.flow_run_id or str(uuid4())
                session.flow_run_id = run_id
                session.active_run_id = run_id
                session.current_model = model
                session.status = "running"
                session.partial_response = ""
                session.active_phase = "planning"
                session.messages.append({"role": "user", "content": display_message})
                session.prompt_messages.append(
                    {"role": "user", "content": prompt_message if not is_resume else request.message}
                )
                if is_resume:
                    session.trace_carrier = carrier
                    session.pending_question = None
                    session.pending_options = []
                else:
                    session.trace_carrier = carrier
                    session.pending_question = None
                    session.pending_options = []
                    session.human_loop_count = 0
                    session.reasoning_summary = ""
                session.active_task = asyncio.create_task(
                    self.run_chat_turn(
                        session_id,
                        run_id,
                        carrier,
                        api_key,
                        model,
                        request_message=None if is_resume else prompt_message,
                        human_answer=request.message if is_resume else None,
                    )
                )
                return {
                    "status": "running",
                    "session_id": session_id,
                    "run_id": run_id,
                    "trace_id": trace_id,
                    "model": model,
                    "otel": {"same_trace": is_resume},
                    "attachments": attachment_names,
                }

    async def get_chat_state(self, session_id: str) -> dict[str, Any]:
        session = self.chat_sessions.get(session_id)
        if session is None:
            return self.empty_chat_state_payload(session_id)
        return self.chat_state_payload(session)


def openai_api_key_from_env() -> str:
    import os

    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise HTTPException(status_code=500, detail="OPENAI_API_KEY is required")
    return api_key
