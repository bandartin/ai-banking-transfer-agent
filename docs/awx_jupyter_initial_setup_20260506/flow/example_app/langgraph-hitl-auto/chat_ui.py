from __future__ import annotations

from typing import Any, Callable

import httpx

from chat_prompts import reasoning_text

DIRECT_INPUT_LABEL = "직접 입력"


def chat_api_base_url() -> str:
    import os

    return os.getenv("CHAT_API_BASE_URL", "http://127.0.0.1:8001").rstrip("/")


def read_chat_state_payload(session_id: str) -> dict[str, Any]:
    with httpx.Client(base_url=chat_api_base_url(), timeout=30.0) as client:
        response = client.get(f"/chat/state/{session_id}")
        response.raise_for_status()
        return response.json()


def send_chat_message_via_api(
    message: str,
    session_id: str,
    model: str,
    attachments: list[str] | None,
    *,
    force_steer: bool = False,
) -> dict[str, Any]:
    with httpx.Client(base_url=chat_api_base_url(), timeout=30.0) as client:
        response = client.post(
            "/chat/send",
            json={
                "message": message,
                "session_id": session_id,
                "model": model,
                "attachments": attachments or [],
                "force_steer": force_steer,
            },
        )
        response.raise_for_status()
        return response.json()


def gradio_chat_messages(payload: dict[str, Any]) -> list[dict[str, str]]:
    messages = [
        {"role": item["role"], "content": item["content"]}
        for item in payload.get("messages", [])
    ]
    partial_response = payload.get("partial_response") or ""
    if partial_response and payload.get("active_phase") == "final_answer":
        messages.append({"role": "assistant", "content": partial_response})
    return messages


def gradio_helper_text(payload: dict[str, Any]) -> str:
    if payload.get("active_run"):
        if payload.get("active_phase") == "planning":
            return "Assistant가 추가 질문이 필요한지 판단 중입니다. 지금 보내면 queue에 쌓입니다."
        return "Assistant가 최종 답변을 작성 중입니다. Send는 queue에 쌓이고, Steer Now는 현재 응답을 끊고 바로 보냅니다."
    if payload.get("status") == "awaiting_human":
        if payload.get("pending_options"):
            return "아래 3개 제안 중 하나를 고르거나, 4번째 '직접 입력'을 선택한 뒤 Message에 답변하면 같은 trace로 이어서 진행합니다."
        return "Assistant 질문에 대한 사람의 답변을 입력하면 같은 trace로 이어서 진행합니다."
    if payload.get("steer_count"):
        return "이번 세션에서는 steer가 한 번 이상 발생했습니다."
    if payload.get("human_loop_count"):
        return "이번 trace에서는 human-in-the-loop가 한 번 이상 실행되었습니다."
    return "대기 중입니다. 첫 메시지를 보내면 Assistant가 먼저 확인 질문을 하고, 사람 답변 후 이어서 진행합니다."


def gradio_timer_update(payload: dict[str, Any]) -> dict[str, Any]:
    return {"active": bool(payload.get("active_run"))}


def gradio_choice_selector_update(payload: dict[str, Any]) -> dict[str, Any]:
    options = payload.get("pending_options") or []
    return {
        "choices": [*options, DIRECT_INPUT_LABEL] if options else [],
        "value": None,
        "visible": payload.get("status") == "awaiting_human" and bool(options),
    }


def gradio_view(
    payload: dict[str, Any],
) -> tuple[
    list[dict[str, str]],
    str,
    str,
    str,
    str,
    str,
    str,
    str,
    str,
    str,
    str,
    dict[str, Any],
    dict[str, Any],
]:
    return (
        gradio_chat_messages(payload),
        payload.get("trace_id") or "",
        payload.get("status") or "idle",
        str(payload.get("human_loop_count", 0)),
        str(payload.get("steer_count", 0)),
        str(payload.get("queue_count", 0)),
        gradio_helper_text(payload),
        reasoning_text(payload.get("reasoning_summary")),
        {"visible": bool(payload.get("can_steer"))},
        gradio_choice_selector_update(payload),
        gradio_timer_update(payload),
    )


def gradio_css() -> str:
    return """
    :root {
      --paper: #f6efe4;
      --panel: #fffaf2;
      --ink: #231b14;
      --muted: #706254;
      --accent: #c55b28;
      --accent-2: #1f5d63;
    }
    .gradio-container {
      background:
        radial-gradient(circle at top left, rgba(197, 91, 40, 0.16), transparent 24%),
        radial-gradient(circle at top right, rgba(31, 93, 99, 0.12), transparent 22%),
        linear-gradient(180deg, #fbf7f0 0%, var(--paper) 100%);
    }
    #hero {
      border: 1px solid rgba(35, 27, 20, 0.08);
      border-radius: 24px;
      background: rgba(255, 250, 242, 0.88);
      box-shadow: 0 20px 70px rgba(35, 27, 20, 0.08);
      padding: 20px 24px;
    }
    #hero h1 {
      font-family: "Iowan Old Style", "Palatino Linotype", Georgia, serif;
      letter-spacing: -0.04em;
      margin: 0 0 10px;
      color: var(--ink);
    }
    #hero p {
      margin: 0;
      color: var(--muted);
      line-height: 1.6;
    }
    #meta-row .gr-box, #chat-shell, #reasoning-box {
      border-radius: 22px;
      border: 1px solid rgba(35, 27, 20, 0.08);
      background: rgba(255, 250, 242, 0.9);
      box-shadow: 0 20px 70px rgba(35, 27, 20, 0.08);
    }
    #chat-shell {
      padding: 10px;
    }
    #reasoning-box {
      padding: 12px 16px;
    }
    #send-btn button {
      background: linear-gradient(135deg, var(--accent), #df7c41);
      color: #fff8ef;
      border: 0;
    }
    #composer-toolbar {
      align-items: center;
      gap: 10px;
      margin: 6px 0 10px;
    }
    #composer-toolbar .gradio-dropdown,
    #composer-toolbar .gradio-button {
      min-height: 42px;
    }
    #model-chip {
      max-width: 220px;
    }
    #attachment-toggle button {
      border: 1px solid rgba(35, 27, 20, 0.12);
      background: rgba(255, 250, 242, 0.92);
      color: var(--ink);
    }
    #attachment-panel {
      border: 1px dashed rgba(35, 27, 20, 0.14);
      border-radius: 18px;
      margin: 0 0 12px;
      padding: 8px;
      background: rgba(255, 250, 242, 0.72);
    }
    #message-box textarea {
      min-height: 58px !important;
    }
    #new-session-btn button {
      border: 1px solid rgba(35, 27, 20, 0.12);
    }
    """


def attachment_button_text(attachment_files: list[str] | None) -> str:
    if not attachment_files:
        return "📎 Attach"
    count = len(attachment_files)
    suffix = "file" if count == 1 else "files"
    return f"📎 {count} {suffix}"


def build_gradio_ui(
    *,
    new_session_id: Callable[[], str],
    available_models: list[str],
    chat_input_lines: int,
) -> Any:
    import gradio as gr

    def toggle_attachment_panel(
        is_open: bool,
        attachment_files: list[str] | None,
    ) -> tuple[bool, Any, Any]:
        next_open = not is_open
        return (
            next_open,
            gr.update(visible=next_open),
            gr.update(value=attachment_button_text(attachment_files)),
        )

    def sync_attachment_button(attachment_files: list[str] | None) -> Any:
        return gr.update(value=attachment_button_text(attachment_files))

    def refresh_view(
        session_id: str,
    ) -> tuple[list[dict[str, str]], str, str, str, str, str, str, str, str, Any, Any, Any]:
        payload = read_chat_state_payload(session_id)
        (
            messages,
            trace_id,
            status,
            interrupt_count,
            steer_count,
            queue_count,
            helper,
            reasoning,
            steer_button_update,
            choice_selector_update,
            timer_update,
        ) = gradio_view(payload)
        return (
            messages,
            session_id,
            session_id,
            trace_id,
            status,
            interrupt_count,
            steer_count,
            queue_count,
            helper,
            reasoning,
            gr.update(**steer_button_update),
            gr.update(**choice_selector_update),
            gr.update(**timer_update),
        )

    def submit_message(
        message: str,
        selected_choice: str | None,
        session_id: str,
        selected_model: str,
        attachment_files: list[str] | None,
    ) -> tuple[list[dict[str, str]], str, str, str, str, str, str, str, str, Any, Any, Any, str, Any, bool, Any]:
        return _submit_message(
            message,
            selected_choice,
            session_id,
            selected_model,
            attachment_files,
            force_steer=False,
        )

    def steer_now(
        message: str,
        selected_choice: str | None,
        session_id: str,
        selected_model: str,
        attachment_files: list[str] | None,
    ) -> tuple[list[dict[str, str]], str, str, str, str, str, str, str, str, Any, Any, Any, str, Any, bool, Any]:
        return _submit_message(
            message,
            selected_choice,
            session_id,
            selected_model,
            attachment_files,
            force_steer=True,
        )

    def _submit_message(
        message: str,
        selected_choice: str | None,
        session_id: str,
        selected_model: str,
        attachment_files: list[str] | None,
        *,
        force_steer: bool,
    ) -> tuple[list[dict[str, str]], str, str, str, str, str, str, str, str, Any, Any, Any, str, Any, bool, Any]:
        active_session_id = session_id or new_session_id()
        composed_message = message.strip()
        if selected_choice and selected_choice != DIRECT_INPUT_LABEL and not composed_message:
            composed_message = selected_choice.strip()
        attachment_paths = attachment_files or []
        if composed_message or attachment_paths:
            send_chat_message_via_api(
                composed_message or "(See attached files)",
                active_session_id,
                selected_model,
                attachment_paths,
                force_steer=force_steer,
            )
        payload = read_chat_state_payload(active_session_id)
        (
            messages,
            trace_id,
            status,
            interrupt_count,
            steer_count,
            queue_count,
            helper,
            reasoning,
            steer_button_update,
            choice_selector_update,
            timer_update,
        ) = gradio_view(payload)
        return (
            messages,
            active_session_id,
            active_session_id,
            trace_id,
            status,
            interrupt_count,
            steer_count,
            queue_count,
            helper,
            reasoning,
            gr.update(**steer_button_update),
            gr.update(**choice_selector_update),
            gr.update(**timer_update),
            "",
            gr.update(value=None, visible=False),
            False,
            gr.update(value=attachment_button_text(None)),
        )

    def reset_session() -> tuple[list[dict[str, str]], str, str, str, str, str, str, str, str, Any, Any, Any, str, Any, bool, Any]:
        session_id = new_session_id()
        payload = read_chat_state_payload(session_id)
        (
            messages,
            trace_id,
            status,
            interrupt_count,
            steer_count,
            queue_count,
            helper,
            reasoning,
            steer_button_update,
            choice_selector_update,
            timer_update,
        ) = gradio_view(payload)
        return (
            messages,
            session_id,
            session_id,
            trace_id,
            status,
            interrupt_count,
            steer_count,
            queue_count,
            helper,
            reasoning,
            gr.update(**steer_button_update),
            gr.update(**choice_selector_update),
            gr.update(**timer_update),
            "",
            gr.update(value=None, visible=False),
            False,
            gr.update(value=attachment_button_text(None)),
        )

    with gr.Blocks(title="LangGraph Human in the Loop", fill_height=True) as demo:
        session_state = gr.State(new_session_id())
        attachment_panel_state = gr.State(False)

        gr.Markdown(
            """
            <div id="hero">
              <h1>Human in the Loop</h1>
              <p>Assistant가 먼저 확인 질문을 던지고, 사람 답변을 받으면 같은 trace에서 이어서 최종 답변을 생성합니다.</p>
            </div>
            """
        )

        with gr.Row(elem_id="meta-row"):
            session_box = gr.Textbox(label="Session ID", interactive=False)
            trace_box = gr.Textbox(label="Trace ID", interactive=False)
            status_box = gr.Textbox(label="Status", interactive=False)
            interrupt_box = gr.Textbox(label="HITL Count", interactive=False)
            steer_box = gr.Textbox(label="Steer Count", interactive=False)
            queue_box = gr.Textbox(label="Queue Count", interactive=False)

        helper_box = gr.Markdown("대기 중입니다. 첫 메시지를 보내면 여기서 실시간 응답을 볼 수 있습니다.")
        reasoning_box = gr.Markdown("아직 reasoning 요약이 없습니다.", elem_id="reasoning-box")

        with gr.Column(elem_id="chat-shell"):
            chatbot = gr.Chatbot(height=520, group_consecutive_messages=False, autoscroll=False, buttons=["copy_all"])
            choice_selector = gr.Radio(label="Suggestions", choices=[], visible=False)
            with gr.Row(elem_id="composer-toolbar"):
                model_dropdown = gr.Dropdown(
                    label="Model",
                    choices=available_models,
                    value=available_models[0],
                    interactive=True,
                    show_label=False,
                    container=False,
                    elem_id="model-chip",
                    scale=2,
                )
                attachment_toggle = gr.Button(
                    "📎 Attach",
                    elem_id="attachment-toggle",
                    variant="secondary",
                    min_width=120,
                )
            attachment_box = gr.File(
                label="Attachments",
                file_count="multiple",
                visible=False,
                show_label=False,
                container=False,
                elem_id="attachment-panel",
            )
            message_box = gr.Textbox(
                label="Message",
                placeholder="첫 요청은 자유 입력, 질문 단계에서는 제안을 고르거나 직접 답변을 입력하세요.",
                lines=chat_input_lines,
                elem_id="message-box",
            )
            with gr.Row():
                send_button = gr.Button("Send / Queue / Resume", elem_id="send-btn", variant="primary")
                steer_button = gr.Button("Steer Now", visible=False)
                new_session_button = gr.Button("New Session", elem_id="new-session-btn")

        timer = gr.Timer(0.35, active=False)

        common_outputs = [
            chatbot,
            session_state,
            session_box,
            trace_box,
            status_box,
            interrupt_box,
            steer_box,
            queue_box,
            helper_box,
            reasoning_box,
            steer_button,
            choice_selector,
            timer,
        ]

        demo.load(
            refresh_view,
            inputs=[session_state],
            outputs=common_outputs,
            queue=False,
        )
        attachment_toggle.click(
            toggle_attachment_panel,
            inputs=[attachment_panel_state, attachment_box],
            outputs=[attachment_panel_state, attachment_box, attachment_toggle],
            queue=False,
        )
        attachment_box.change(
            sync_attachment_button,
            inputs=[attachment_box],
            outputs=[attachment_toggle],
            queue=False,
        )
        timer.tick(
            refresh_view,
            inputs=[session_state],
            outputs=common_outputs,
            queue=False,
        )
        send_button.click(
            submit_message,
            inputs=[message_box, choice_selector, session_state, model_dropdown, attachment_box],
            outputs=common_outputs + [message_box, attachment_box, attachment_panel_state, attachment_toggle],
            queue=False,
        )
        steer_button.click(
            steer_now,
            inputs=[message_box, choice_selector, session_state, model_dropdown, attachment_box],
            outputs=common_outputs + [message_box, attachment_box, attachment_panel_state, attachment_toggle],
            queue=False,
        )
        message_box.submit(
            submit_message,
            inputs=[message_box, choice_selector, session_state, model_dropdown, attachment_box],
            outputs=common_outputs + [message_box, attachment_box, attachment_panel_state, attachment_toggle],
            queue=False,
        )
        new_session_button.click(
            reset_session,
            outputs=common_outputs + [message_box, attachment_box, attachment_panel_state, attachment_toggle],
            queue=False,
        )

    return demo
