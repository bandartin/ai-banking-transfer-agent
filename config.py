"""Application configuration loaded from environment variables."""

import os
from dotenv import load_dotenv

load_dotenv()

# ── LangSmith: set env vars before LangChain/LangGraph imports ───────────────
# LangGraph automatically picks these up via langchain_core callbacks.
_LS_API_KEY = os.getenv("LANGCHAIN_API_KEY", "")
if _LS_API_KEY and os.getenv("LANGCHAIN_TRACING_V2", "").lower() == "true":
    os.environ.setdefault("LANGCHAIN_TRACING_V2", "true")
    os.environ.setdefault("LANGCHAIN_API_KEY", _LS_API_KEY)
    os.environ.setdefault("LANGCHAIN_PROJECT", os.getenv("LANGCHAIN_PROJECT", "banking-transfer-agent"))
    os.environ.setdefault("LANGCHAIN_ENDPOINT", os.getenv("LANGCHAIN_ENDPOINT", "https://api.smith.langchain.com"))


class Config:
    # Flask
    SECRET_KEY: str = os.getenv("FLASK_SECRET_KEY", "demo-secret-key-2024")
    DEBUG: bool = os.getenv("FLASK_ENV", "development") == "development"
    PORT: int = int(os.getenv("FLASK_PORT", "8000"))

    # Database
    SQLALCHEMY_DATABASE_URI: str = os.getenv("DATABASE_URL", "sqlite:///banking_demo.db")
    SQLALCHEMY_TRACK_MODIFICATIONS: bool = False

    # LLM provider: "deterministic" | "openai" | "anthropic"
    LLM_PROVIDER: str = os.getenv("LLM_PROVIDER", "deterministic")
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
    OPENAI_MODEL: str = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "")
    ANTHROPIC_MODEL: str = os.getenv("ANTHROPIC_MODEL", "claude-haiku-4-5-20251001")

    # LangSmith
    LANGSMITH_ENABLED: bool = (
        bool(_LS_API_KEY) and os.getenv("LANGCHAIN_TRACING_V2", "").lower() == "true"
    )
    LANGSMITH_PROJECT: str = os.getenv("LANGCHAIN_PROJECT", "banking-transfer-agent")

    # Business rules
    INTERBANK_FEE: int = int(os.getenv("INTERBANK_FEE", "500"))
    OTP_THRESHOLD: int = int(os.getenv("OTP_THRESHOLD", "3000000"))
    DEMO_OTP_CODE: str = os.getenv("DEMO_OTP_CODE", "123456")

    # Demo defaults
    DEMO_USER_ID: int = int(os.getenv("DEMO_USER_ID", "1"))
    SOURCE_BANK_NAME: str = "으뜸은행"
