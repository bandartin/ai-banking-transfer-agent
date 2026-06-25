from __future__ import annotations

import os
from pathlib import Path


DEFAULT_ATTACHMENT_PREVIEW_CHARS = 2000
TEXT_EXTENSIONS = {
    ".txt",
    ".md",
    ".markdown",
    ".py",
    ".js",
    ".ts",
    ".tsx",
    ".jsx",
    ".json",
    ".yaml",
    ".yml",
    ".toml",
    ".ini",
    ".cfg",
    ".csv",
    ".log",
    ".xml",
    ".html",
    ".css",
    ".sql",
}


def available_models(default_model: str) -> list[str]:
    raw = os.getenv("OPENAI_MODELS", "").strip()
    if not raw:
        return [default_model]
    models = [item.strip() for item in raw.split(",") if item.strip()]
    if default_model not in models:
        models.insert(0, default_model)
    return models


def attachment_context(paths: list[str] | None) -> tuple[list[str], str]:
    if not paths:
        return [], ""

    names: list[str] = []
    sections: list[str] = []
    for raw_path in paths:
        if not raw_path:
            continue
        path = Path(raw_path)
        names.append(path.name)
        if not path.exists():
            sections.append(f"[{path.name}] File path was provided but the file no longer exists.")
            continue
        if path.suffix.lower() not in TEXT_EXTENSIONS:
            sections.append(f"[{path.name}] Binary or unsupported file type attached.")
            continue
        try:
            content = path.read_text(encoding="utf-8", errors="ignore").strip()
        except OSError:
            sections.append(f"[{path.name}] File could not be read.")
            continue
        preview = content[:DEFAULT_ATTACHMENT_PREVIEW_CHARS]
        sections.append(f"[{path.name}]\n{preview}")
    return names, "\n\n".join(sections).strip()


def render_user_message(message: str, attachment_names: list[str]) -> str:
    content = message.strip()
    if not attachment_names:
        return content
    attached = "\n".join(f"- {name}" for name in attachment_names)
    return f"{content}\n\n[Attached files]\n{attached}".strip()


def render_prompt_message(message: str, attachment_blob: str) -> str:
    content = message.strip()
    if not attachment_blob:
        return content
    return f"{content}\n\nAttached file context:\n{attachment_blob}".strip()
