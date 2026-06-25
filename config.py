"""Application configuration loaded from environment variables."""

import os
from dotenv import load_dotenv

load_dotenv()

# Banking prompts and tool outputs can contain account, recipient, or memo data.
# Keep LangChain/OpenLLMetry content capture off unless an environment-specific
# redaction policy explicitly enables it.
os.environ.setdefault("TRACELOOP_TRACE_CONTENT", "false")

# ── LangSmith: set env vars before LangChain/LangGraph imports ───────────────
# LangGraph automatically picks these up via langchain_core callbacks.
_LS_API_KEY = os.getenv("LANGCHAIN_API_KEY", "")
if _LS_API_KEY and os.getenv("LANGCHAIN_TRACING_V2", "").lower() == "true":
    os.environ.setdefault("LANGCHAIN_TRACING_V2", "true")
    os.environ.setdefault("LANGCHAIN_API_KEY", _LS_API_KEY)
    os.environ.setdefault("LANGCHAIN_PROJECT", os.getenv("LANGCHAIN_PROJECT", "banking-transfer-agent"))
    os.environ.setdefault("LANGCHAIN_ENDPOINT", os.getenv("LANGCHAIN_ENDPOINT", "https://api.smith.langchain.com"))

if os.getenv("LANGCHAIN_OTEL_INSTRUMENTATION_ENABLED", "true").lower() == "true":
    try:
        from src.awx_runtime.observability import initialize_langchain_instrumentation

        initialize_langchain_instrumentation()
    except Exception:
        pass


class Config:
    # Flask
    SECRET_KEY: str = os.getenv("FLASK_SECRET_KEY", "demo-secret-key-2024")
    DEBUG: bool = os.getenv("FLASK_ENV", "development") == "development"
    PORT: int = int(os.getenv("FLASK_PORT", "8000"))

    # Database
    SQLALCHEMY_DATABASE_URI: str = os.getenv("DATABASE_URL", "sqlite:///banking_demo.db")
    SQLALCHEMY_TRACK_MODIFICATIONS: bool = False

    # LangGraph checkpointer (SqliteSaver) — 멀티턴 상태 영속화
    CHECKPOINT_DB_PATH: str = os.getenv("CHECKPOINT_DB_PATH", "banking_checkpoints.db")

    # LLM provider: "openai" | "deterministic"
    # 기본은 openai — OPENAI_API_KEY 가 없으면 자동으로 결정론 모드로 폴백한다.
    LLM_PROVIDER: str = os.getenv("LLM_PROVIDER", "openai")
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
    OPENAI_MODEL: str = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "")
    ANTHROPIC_MODEL: str = os.getenv("ANTHROPIC_MODEL", "claude-haiku-4-5-20251001")

    # OpenAI Tool Calling (Phase 1: read-only banking/knowledge/calculator tools)
    TOOL_CALLING_ENABLED: bool = os.getenv("TOOL_CALLING_ENABLED", "true").lower() == "true"
    TOOL_CALLING_TRANSFER_PREP_ENABLED: bool = os.getenv("TOOL_CALLING_TRANSFER_PREP_ENABLED", "false").lower() == "true"
    TOOL_CALLING_AWX_MCP_ENABLED: bool = os.getenv("TOOL_CALLING_AWX_MCP_ENABLED", "false").lower() == "true"
    TOOL_CALLING_AWX_MCP_ALLOWLIST: str = os.getenv("TOOL_CALLING_AWX_MCP_ALLOWLIST", "")
    OPENAI_TOOL_MODEL: str = os.getenv("OPENAI_TOOL_MODEL", "") or OPENAI_MODEL
    TOOL_CALLING_MAX_STEPS: int = int(os.getenv("TOOL_CALLING_MAX_STEPS", "4"))

    # AWX credential/resource metadata (optional; local .env fallback remains supported)
    AWX_CREDENTIAL_SERVICE_ID: str = os.getenv("AWX_CREDENTIAL_SERVICE_ID", "")
    AWX_CREDENTIAL_PROVIDER_ALIAS: str = os.getenv("AWX_CREDENTIAL_PROVIDER_ALIAS", "OpenAI")
    AWX_CREDENTIAL_SERVICE_TYPE_NAME: str = os.getenv("AWX_CREDENTIAL_SERVICE_TYPE_NAME", "LLM")
    AWX_CREDENTIAL_VARIABLE_NAME: str = os.getenv("AWX_CREDENTIAL_VARIABLE_NAME", "OPENAI_API_KEY")
    AWX_EXTERNAL_RESOURCE_SOLUTION_ID: str = os.getenv("AWX_EXTERNAL_RESOURCE_SOLUTION_ID", "BUILDER")
    AWX_MCP_SERVER_NAME: str = os.getenv("AWX_MCP_SERVER_NAME", os.getenv("MCP_SERVER_NAME", ""))
    AWX_MCP_SERVICE_ID: str = os.getenv("AWX_MCP_SERVICE_ID", os.getenv("MCP_SERVICE_ID", ""))

    # Integration adapters
    # BANKING_ADAPTER:
    #   mock = current SQLAlchemy demo schema
    #   ibk  = real IBK adapter placeholder until interface specs are supplied
    BANKING_ADAPTER: str = os.getenv("BANKING_ADAPTER", "mock")
    TRANSFER_EXECUTION_MODE: str = os.getenv("TRANSFER_EXECUTION_MODE", "mock")  # mock | dry_run | live
    KNOWLEDGE_ADAPTER: str = os.getenv("KNOWLEDGE_ADAPTER", "mock")  # mock | awx

    # LangSmith
    LANGSMITH_ENABLED: bool = (
        bool(_LS_API_KEY) and os.getenv("LANGCHAIN_TRACING_V2", "").lower() == "true"
    )
    LANGSMITH_PROJECT: str = os.getenv("LANGCHAIN_PROJECT", "banking-transfer-agent")
    LANGCHAIN_OTEL_INSTRUMENTATION_ENABLED: bool = (
        os.getenv("LANGCHAIN_OTEL_INSTRUMENTATION_ENABLED", "true").lower() == "true"
    )
    TRACELOOP_TRACE_CONTENT: str = os.getenv("TRACELOOP_TRACE_CONTENT", "false")

    # Business rules
    INTERBANK_FEE: int = int(os.getenv("INTERBANK_FEE", "500"))
    OTP_THRESHOLD: int = int(os.getenv("OTP_THRESHOLD", "3000000"))
    DEMO_OTP_CODE: str = os.getenv("DEMO_OTP_CODE", "123456")

    # Demo defaults
    DEMO_USER_ID: int = int(os.getenv("DEMO_USER_ID", "1"))
    SOURCE_BANK_NAME: str = "으뜸은행"
