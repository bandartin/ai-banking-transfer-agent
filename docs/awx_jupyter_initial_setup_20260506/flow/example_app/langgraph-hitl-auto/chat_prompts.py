from __future__ import annotations

import re
from typing import Any


def planner_prompt_messages(history: list[dict[str, str]]) -> list[dict[str, str]]:
    return [
        {
            "role": "system",
            "content": (
                "You are in a human-in-the-loop workflow. "
                "Decide whether you already have enough information to produce the final answer. "
                "If more information is needed, ask exactly one concise follow-up question. "
                "If no more information is needed, do not ask a question and proceed to the final answer stage. "
                "Return only one of these formats with no extra text. "
                "ASK\n"
                "REASON: <one short sentence>\n"
                "QUESTION: <question>\n"
                "OPTIONS:\n"
                "1. <option one>\n"
                "2. <option two>\n"
                "3. <option three>\n"
                "or\n"
                "FINAL\n"
                "REASON: <one short sentence>\n"
                "When you return ASK, always provide exactly three concrete options in Korean. "
                "Do not include markdown, bullets other than 1-3, or any explanation outside the format."
            ),
        },
        *history,
    ]


def final_prompt_messages(history: list[dict[str, str]]) -> list[dict[str, str]]:
    return [
        {
            "role": "system",
            "content": (
                "You are continuing a human-in-the-loop workflow. "
                "The human has answered your follow-up question. "
                "Now provide the final helpful response."
            ),
        },
        *history,
    ]


def parse_structured_question(raw_text: str) -> tuple[str, list[str]]:
    text = raw_text.strip()
    question_match = re.search(r"QUESTION:\s*(.*?)(?:\n\s*OPTIONS:|\s+OPTIONS:)", text, re.IGNORECASE | re.DOTALL)
    options_block_match = re.search(r"OPTIONS:\s*(.*)$", text, re.IGNORECASE | re.DOTALL)
    if not question_match or not options_block_match:
        return raw_text.strip(), []
    question = re.sub(r"\s+", " ", question_match.group(1)).strip()
    options_blob = options_block_match.group(1).strip()
    other_match = re.search(r"(?:^|\n|\s)OTHER:\s*(.*)$", options_blob, re.IGNORECASE | re.DOTALL)
    if other_match:
        options_blob = options_blob[:other_match.start()].strip()
    option_matches = re.findall(
        r"(?:^|\n)\s*\d+\.\s*(.*?)(?=(?:\n\s*\d+\.|\n\s*OTHER:|$))",
        options_blob,
        re.DOTALL,
    )
    flattened = re.sub(r"\s+", " ", options_blob)
    if len(option_matches) <= 1 and re.search(r"\s2\.\s", flattened):
        option_matches = re.findall(r"\d+\.\s*(.*?)(?=\s+\d+\.|$)", flattened)
    options = [re.sub(r"\s+", " ", item).strip() for item in option_matches if re.sub(r"\s+", " ", item).strip()]
    options = options[:3]
    if other_match:
        other_label = re.sub(r"\s+", " ", other_match.group(1)).strip() or "기타"
        if other_label not in options and len(options) < 3:
            options.append(other_label)
    return question, options


def parse_planner_output(raw_text: str) -> tuple[str, str, str, list[str]]:
    text = raw_text.strip()
    normalized = text.upper()
    if normalized.startswith("FINAL"):
        reason_match = re.search(r"REASON:\s*(.*)$", text, re.IGNORECASE | re.DOTALL)
        reason = reason_match.group(1).strip() if reason_match else ""
        return "final", reason, "", []

    ask_text = text
    if normalized.startswith("ASK"):
        ask_text = text[3:].strip()

    reason_match = re.search(r"REASON:\s*(.*?)\s+QUESTION:", ask_text, re.IGNORECASE | re.DOTALL)
    reason = reason_match.group(1).strip() if reason_match else ""
    question, options = parse_structured_question(ask_text)
    if question:
        return "ask", reason, question, options
    return "final", reason, "", []


def reasoning_text(reasoning_summary: str | None) -> str:
    if not reasoning_summary:
        return "아직 reasoning 요약이 없습니다."
    return reasoning_summary
