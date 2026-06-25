from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from pydantic import BaseModel, Field, model_validator

from openai.types.chat import ChatCompletionMessageParam, ChatCompletionRole
from openai.types.shared import ChatModel


class ChatRequest(BaseModel):
    model: ChatModel | str | None = None
    messages: list[ChatCompletionMessageParam] = Field(default_factory=list)
    message: str | None = None
    stream: bool = False

    @model_validator(mode="after")
    def _populate_messages_from_legacy_field(self):
        if self.messages:
            self.messages = [_normalize_message(message) for message in self.messages]
            return self
        if self.message:
            self.messages = [{"role": "user", "content": self.message}]
        return self

    model_config = {"populate_by_name": True}


def _normalize_message(message: ChatCompletionMessageParam) -> ChatCompletionMessageParam:
    if not isinstance(message, Mapping):
        return message

    message_dict: dict[str, Any] = dict(message)
    content = message_dict.get("content")

    # Pydantic may keep OpenAI TypedDict iterable content as ValidatorIterator.
    if isinstance(content, Iterable) and not isinstance(content, (str, bytes, list, dict)):
        message_dict["content"] = list(content)
    return message_dict
