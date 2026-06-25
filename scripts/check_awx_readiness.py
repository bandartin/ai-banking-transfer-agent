"""Check local readiness for AWX/IBK integration handoff.

This script intentionally uses only the Python standard library so it can run
before project dependencies are installed.  It does not prove that AWX Portal
credentials or knowledge collections work end-to-end; it tells you whether the
local source tree and environment contain the pieces needed to perform that
verification in the real AWX runtime.

Examples:
    python scripts/check_awx_readiness.py
    python scripts/check_awx_readiness.py --json
    python scripts/check_awx_readiness.py --strict
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import subprocess
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
TRUE_VALUES = {"1", "true", "yes", "y", "on"}
FALSE_VALUES = {"0", "false", "no", "n", "off"}


@dataclass
class CheckResult:
    name: str
    status: str
    detail: str


def main() -> int:
    args = _parse_args()
    env = _load_env_file(REPO_ROOT / ".env")
    merged = {**env, **os.environ}

    checks = [
        _check_file("AWX run script", REPO_ROOT / "awx" / "run-application.sh"),
        _check_file("AWX bootstrap manifest", REPO_ROOT / "awx" / "awx-bootstrap.json"),
        _check_file("AWX pyproject", REPO_ROOT / "awx" / "pyproject.toml"),
        _check_file("Integration package", REPO_ROOT / "src" / "integrations" / "factory.py"),
        _check_env_value("BANKING_ADAPTER", merged, allowed={"mock", "ibk"}),
        _check_env_value("TRANSFER_EXECUTION_MODE", merged, allowed={"mock", "dry_run", "live"}),
        _check_env_value("KNOWLEDGE_ADAPTER", merged, allowed={"mock", "awx"}),
        _check_bool_env("TOOL_CALLING_ENABLED", merged, default=True),
        _check_bool_env("TOOL_CALLING_TRANSFER_PREP_ENABLED", merged, default=False),
        _check_bool_env("TOOL_CALLING_AWX_MCP_ENABLED", merged, default=False),
        _check_bool_env("LANGCHAIN_OTEL_INSTRUMENTATION_ENABLED", merged, default=True),
        _check_trace_content_policy(merged),
        _check_tool_calling_rollout(merged),
        _check_awx_mcp_rollout(merged),
        _check_dependency_pin("langchain"),
        _check_dependency_pin("langchain-openai"),
        _check_dependency_pin("opentelemetry-instrumentation-flask"),
        _check_dependency_pin("opentelemetry-instrumentation-langchain"),
        _check_awx_otel_entrypoint(),
        _check_live_safety(merged),
        _check_awx_credential_config(merged),
        _check_awx_sdk(),
        _check_python_alias(),
    ]

    exit_code = _exit_code(checks, strict=args.strict)
    report_path = None
    if args.report:
        report = _build_readiness_report(checks, strict=args.strict, env=merged, exit_code=exit_code)
        report_path = _write_report(Path(args.report), report)

    if args.json:
        print(json.dumps([asdict(c) for c in checks], ensure_ascii=False, indent=2))
    else:
        _print_text(checks)
        if report_path:
            print(f"\nReadiness report written: {report_path}")

    return exit_code


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    parser.add_argument("--strict", action="store_true", help="Treat warnings as a non-zero exit.")
    parser.add_argument("--report", help="Write a sanitized readiness report JSON artifact to this path.")
    return parser.parse_args()


def _load_env_file(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def _check_file(name: str, path: Path) -> CheckResult:
    if path.exists():
        return CheckResult(name, "ok", str(path.relative_to(REPO_ROOT)))
    return CheckResult(name, "error", f"Missing {path.relative_to(REPO_ROOT)}")


def _check_env_value(name: str, env: dict[str, str], *, allowed: set[str]) -> CheckResult:
    value = (env.get(name) or "").strip().lower()
    if not value:
        default = "mock" if name != "TRANSFER_EXECUTION_MODE" else "mock"
        return CheckResult(name, "warning", f"Not set; application default is {default!r}.")
    if value not in allowed:
        return CheckResult(name, "error", f"{name}={value!r} is invalid. Allowed: {sorted(allowed)}")
    return CheckResult(name, "ok", f"{name}={value}")


def _env_bool(name: str, env: dict[str, str], *, default: bool) -> tuple[bool, bool, str]:
    raw = (env.get(name) or "").strip()
    if not raw:
        return default, True, f"default={str(default).lower()}"
    value = raw.lower()
    if value in TRUE_VALUES:
        return True, True, f"{name}=true"
    if value in FALSE_VALUES:
        return False, True, f"{name}=false"
    return default, False, f"{name}={raw!r} is invalid. Use true or false."


def _check_bool_env(name: str, env: dict[str, str], *, default: bool) -> CheckResult:
    _value, valid, detail = _env_bool(name, env, default=default)
    if not valid:
        return CheckResult(name, "error", detail)
    return CheckResult(name, "ok", detail)


def _check_trace_content_policy(env: dict[str, str]) -> CheckResult:
    trace_content, trace_valid, trace_detail = _env_bool("TRACELOOP_TRACE_CONTENT", env, default=False)
    if not trace_valid:
        return CheckResult("Trace content policy", "error", trace_detail)
    langchain_otel_enabled, langchain_valid, _ = _env_bool(
        "LANGCHAIN_OTEL_INSTRUMENTATION_ENABLED",
        env,
        default=True,
    )
    if not langchain_valid:
        return CheckResult(
            "Trace content policy",
            "error",
            "LANGCHAIN_OTEL_INSTRUMENTATION_ENABLED must be true or false before trace policy can be evaluated.",
        )
    if trace_content:
        return CheckResult(
            "Trace content policy",
            "error",
            "TRACELOOP_TRACE_CONTENT=true may persist banking prompts, responses, and tool outputs. Set it to false.",
        )
    detail = "TRACELOOP_TRACE_CONTENT=false"
    if langchain_otel_enabled:
        detail += ", LangChain instrumentation may stay enabled without content capture."
    else:
        detail += ", LangChain instrumentation disabled."
    return CheckResult("Trace content policy", "ok", detail)


def _check_tool_calling_rollout(env: dict[str, str]) -> CheckResult:
    enabled, enabled_valid, enabled_detail = _env_bool("TOOL_CALLING_ENABLED", env, default=True)
    transfer_prep, prep_valid, prep_detail = _env_bool("TOOL_CALLING_TRANSFER_PREP_ENABLED", env, default=False)
    if not enabled_valid:
        return CheckResult("Tool calling rollout", "error", enabled_detail)
    if not prep_valid:
        return CheckResult("Tool calling rollout", "error", prep_detail)
    if transfer_prep and not enabled:
        return CheckResult(
            "Tool calling rollout",
            "warning",
            "TOOL_CALLING_TRANSFER_PREP_ENABLED=true has no effect while TOOL_CALLING_ENABLED=false.",
        )

    execution_mode = (env.get("TRANSFER_EXECUTION_MODE") or "mock").strip().lower()
    if transfer_prep:
        suffix = ""
        if execution_mode == "live":
            suffix = " Live mode also requires a fresh HITL/OTP dry-run sign-off."
        return CheckResult(
            "Tool calling rollout",
            "warning",
            "Transfer-prep tools are enabled; verify Phase 5 regression, audit masking, and HITL confirmation before production."
            + suffix,
        )
    if enabled:
        return CheckResult("Tool calling rollout", "ok", "Read-only tool calling enabled; transfer-prep tools disabled.")
    return CheckResult("Tool calling rollout", "ok", "Tool calling disabled; deterministic fallback remains active.")


def _check_awx_mcp_rollout(env: dict[str, str]) -> CheckResult:
    enabled, enabled_valid, enabled_detail = _env_bool("TOOL_CALLING_AWX_MCP_ENABLED", env, default=False)
    if not enabled_valid:
        return CheckResult("AWX MCP tool rollout", "error", enabled_detail)
    if not enabled:
        return CheckResult("AWX MCP tool rollout", "ok", "AWX MCP tool adapter disabled.")

    tool_calling_enabled, tool_calling_valid, _ = _env_bool("TOOL_CALLING_ENABLED", env, default=True)
    if not tool_calling_valid:
        return CheckResult(
            "AWX MCP tool rollout",
            "error",
            "TOOL_CALLING_ENABLED must be true or false before AWX MCP rollout can be evaluated.",
        )
    if not tool_calling_enabled:
        return CheckResult(
            "AWX MCP tool rollout",
            "warning",
            "TOOL_CALLING_AWX_MCP_ENABLED=true has no effect while TOOL_CALLING_ENABLED=false.",
        )

    allowlist = (env.get("TOOL_CALLING_AWX_MCP_ALLOWLIST") or "").strip()
    if not allowlist:
        return CheckResult(
            "AWX MCP tool rollout",
            "warning",
            "AWX MCP adapter is enabled, but TOOL_CALLING_AWX_MCP_ALLOWLIST is empty; no MCP tools will be exposed.",
        )

    try:
        parsed = _parse_awx_mcp_allowlist_for_readiness(allowlist)
    except ValueError as exc:
        return CheckResult("AWX MCP tool rollout", "error", str(exc))

    manifest_warning = _awx_mcp_manifest_warning()
    detail = f"{len(parsed)} allowlisted MCP tool(s); side effects limited to read/prepare."
    if manifest_warning:
        return CheckResult("AWX MCP tool rollout", "warning", f"{detail} {manifest_warning}")
    return CheckResult("AWX MCP tool rollout", "ok", detail)


def _parse_awx_mcp_allowlist_for_readiness(raw: str) -> dict[str, str]:
    if not raw:
        return {}
    if raw[0] in "[{":
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"TOOL_CALLING_AWX_MCP_ALLOWLIST is invalid JSON: {exc}") from exc
        items: dict[str, str] = {}
        if isinstance(payload, dict):
            for name, value in payload.items():
                if isinstance(value, str):
                    items[str(name)] = value
                elif isinstance(value, dict):
                    items[str(name)] = str(value.get("side_effect") or value.get("sideEffect") or "")
                else:
                    raise ValueError(f"AWX MCP allowlist entry for {name!r} must be a string or object.")
        elif isinstance(payload, list):
            for item in payload:
                if not isinstance(item, dict):
                    raise ValueError("AWX MCP allowlist list entries must be objects.")
                items[str(item.get("name") or "")] = str(item.get("side_effect") or item.get("sideEffect") or "")
        else:
            raise ValueError("AWX MCP allowlist must be a JSON object, JSON list, or CSV string.")
    else:
        items = {}
        for raw_entry in raw.split(","):
            entry = raw_entry.strip()
            if not entry:
                continue
            if ":" not in entry:
                raise ValueError("AWX MCP allowlist CSV entries must use '<tool_name>:<read|prepare>'.")
            name, side_effect = entry.split(":", 1)
            items[name.strip()] = side_effect.strip()

    parsed: dict[str, str] = {}
    for name, side_effect in items.items():
        normalized_name = str(name or "").strip()
        normalized_effect = str(side_effect or "").strip().lower()
        if not normalized_name:
            raise ValueError("AWX MCP allowlist contains an empty tool name.")
        if normalized_effect not in {"read", "prepare"}:
            raise ValueError(
                f"AWX MCP tool {normalized_name!r} uses side_effect={normalized_effect!r}; only read and prepare are allowed."
            )
        parsed[normalized_name] = normalized_effect
    return parsed


def _awx_mcp_manifest_warning() -> str:
    manifest_path = REPO_ROOT / "awx" / "awx-bootstrap.json"
    if not manifest_path.exists():
        return "awx/awx-bootstrap.json is missing; MCP prefetch cannot be verified."
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return "awx/awx-bootstrap.json is not valid JSON; MCP prefetch cannot be verified."
    if not bool(manifest.get("prefetch_mcp", False)):
        return "Set awx/awx-bootstrap.json prefetch_mcp=true before AWX MCP rollout."
    return ""


def _check_dependency_pin(package_name: str) -> CheckResult:
    requirements = REPO_ROOT / "requirements.txt"
    if not requirements.exists():
        return CheckResult(f"Dependency: {package_name}", "error", "requirements.txt is missing.")

    normalized = package_name.lower()
    for raw in requirements.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        lower = line.lower()
        if lower.startswith(normalized + "=="):
            return CheckResult(f"Dependency: {package_name}", "ok", line)
        if lower == normalized or lower.startswith(normalized + ">") or lower.startswith(normalized + "~"):
            return CheckResult(
                f"Dependency: {package_name}",
                "warning",
                f"{line} is present but not exactly pinned with ==.",
            )
    return CheckResult(f"Dependency: {package_name}", "error", f"{package_name} is missing from requirements.txt.")


def _check_awx_otel_entrypoint() -> CheckResult:
    run_script = REPO_ROOT / "awx" / "run-application.sh"
    if not run_script.exists():
        return CheckResult("AWX OTel entrypoint", "error", "awx/run-application.sh is missing.")
    text = run_script.read_text(encoding="utf-8")
    if "opentelemetry-instrument" not in text:
        return CheckResult(
            "AWX OTel entrypoint",
            "error",
            "awx/run-application.sh should launch the app with opentelemetry-instrument.",
        )
    return CheckResult("AWX OTel entrypoint", "ok", "awx/run-application.sh uses opentelemetry-instrument.")


def _check_live_safety(env: dict[str, str]) -> CheckResult:
    banking_adapter = (env.get("BANKING_ADAPTER") or "mock").strip().lower()
    execution_mode = (env.get("TRANSFER_EXECUTION_MODE") or "mock").strip().lower()
    if execution_mode == "live" and banking_adapter == "mock":
        return CheckResult(
            "Live execution safety",
            "error",
            "TRANSFER_EXECUTION_MODE=live cannot be used with BANKING_ADAPTER=mock.",
        )
    if execution_mode == "live" and banking_adapter != "ibk":
        return CheckResult("Live execution safety", "error", "Live execution requires BANKING_ADAPTER=ibk.")
    return CheckResult("Live execution safety", "ok", f"adapter={banking_adapter}, mode={execution_mode}")


def _check_awx_credential_config(env: dict[str, str]) -> CheckResult:
    knowledge_adapter = (env.get("KNOWLEDGE_ADAPTER") or "mock").strip().lower()
    llm_provider = (env.get("LLM_PROVIDER") or "openai").strip().lower()
    service_id = (env.get("AWX_CREDENTIAL_SERVICE_ID") or "").strip()
    if knowledge_adapter == "awx" or llm_provider == "openai":
        if not service_id:
            return CheckResult(
                "AWX credential metadata",
                "warning",
                "AWX_CREDENTIAL_SERVICE_ID is empty. Local OPENAI_API_KEY fallback may work, but Portal credential verification cannot run.",
            )
    return CheckResult("AWX credential metadata", "ok", f"service_id={service_id or '(not required for mock)'}")


def _check_awx_sdk() -> CheckResult:
    awx_spec = importlib.util.find_spec("awx")
    if awx_spec is None:
        return CheckResult(
            "AWX SDK import",
            "warning",
            "Python cannot import package 'awx' here. This is expected outside the AWX runtime; adapters will fall back/no-op locally.",
        )
    missing = []
    for module in ("awx.resources", "awx.observability"):
        if importlib.util.find_spec(module) is None:
            missing.append(module)
    if missing:
        return CheckResult("AWX SDK import", "warning", f"awx package exists but missing: {', '.join(missing)}")
    return CheckResult("AWX SDK import", "ok", "awx.resources and awx.observability are importable.")


def _check_python_alias() -> CheckResult:
    # A Windows Store alias often reports python.exe version 0.0.0.0 and cannot
    # run project commands reliably.  We do not fail on this, but it is useful
    # to flag before someone tries to run pytest locally.
    import sys

    executable = Path(sys.executable)
    if "WindowsApps" in str(executable):
        return CheckResult("Python runtime", "warning", f"Windows Store alias detected: {executable}")
    return CheckResult("Python runtime", "ok", str(executable))


def _exit_code(checks: list[CheckResult], *, strict: bool) -> int:
    has_error = any(c.status == "error" for c in checks)
    has_warning = any(c.status == "warning" for c in checks)
    if has_error or (strict and has_warning):
        return 1
    return 0


def _build_readiness_report(
    checks: list[CheckResult],
    *,
    strict: bool,
    env: dict[str, str],
    exit_code: int,
) -> dict[str, Any]:
    """Build an operator evidence artifact without credential values."""
    counts = {"ok": 0, "warning": 0, "error": 0}
    for check in checks:
        if check.status in counts:
            counts[check.status] += 1

    return {
        "schema_version": "tool_calling_readiness_report.v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "repo": _git_metadata(),
        "strict": strict,
        "exit_code": exit_code,
        "summary": counts,
        "runtime_flags": _safe_runtime_flags(env),
        "checks": [asdict(_sanitize_check(check)) for check in checks],
    }


def _write_report(path: Path, report: dict[str, Any]) -> Path:
    output_path = path if path.is_absolute() else REPO_ROOT / path
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return output_path


def _sanitize_check(check: CheckResult) -> CheckResult:
    if check.name == "AWX credential metadata":
        if "is empty" in check.detail:
            return check
        return CheckResult(check.name, check.status, "service_id=(present)")
    if check.name == "Python runtime":
        if "Windows Store alias" in check.detail:
            return CheckResult(check.name, check.status, "Windows Store Python alias detected.")
        return CheckResult(check.name, check.status, "Python runtime path verified.")
    detail = check.detail.replace(str(REPO_ROOT), "<repo>")
    return CheckResult(check.name, check.status, detail)


def _safe_runtime_flags(env: dict[str, str]) -> dict[str, str]:
    return {
        "BANKING_ADAPTER": _safe_choice(env, "BANKING_ADAPTER", default="mock", allowed={"mock", "ibk"}),
        "TRANSFER_EXECUTION_MODE": _safe_choice(
            env,
            "TRANSFER_EXECUTION_MODE",
            default="mock",
            allowed={"mock", "dry_run", "live"},
        ),
        "KNOWLEDGE_ADAPTER": _safe_choice(env, "KNOWLEDGE_ADAPTER", default="mock", allowed={"mock", "awx"}),
        "LLM_PROVIDER": _safe_choice(
            env,
            "LLM_PROVIDER",
            default="openai",
            allowed={"openai", "deterministic", "mock"},
        ),
        "TOOL_CALLING_ENABLED": _safe_bool(env, "TOOL_CALLING_ENABLED", default=True),
        "TOOL_CALLING_TRANSFER_PREP_ENABLED": _safe_bool(
            env,
            "TOOL_CALLING_TRANSFER_PREP_ENABLED",
            default=False,
        ),
        "TOOL_CALLING_AWX_MCP_ENABLED": _safe_bool(env, "TOOL_CALLING_AWX_MCP_ENABLED", default=False),
        "TOOL_CALLING_AWX_MCP_ALLOWLIST_COUNT": str(
            _safe_awx_mcp_allowlist_count(env.get("TOOL_CALLING_AWX_MCP_ALLOWLIST") or "")
        ),
        "LANGCHAIN_OTEL_INSTRUMENTATION_ENABLED": _safe_bool(
            env,
            "LANGCHAIN_OTEL_INSTRUMENTATION_ENABLED",
            default=True,
        ),
        "TRACELOOP_TRACE_CONTENT": _safe_bool(env, "TRACELOOP_TRACE_CONTENT", default=False),
    }


def _safe_awx_mcp_allowlist_count(raw: str) -> int | str:
    try:
        return len(_parse_awx_mcp_allowlist_for_readiness(raw.strip()))
    except ValueError:
        return "invalid"


def _safe_choice(env: dict[str, str], name: str, *, default: str, allowed: set[str]) -> str:
    value = (env.get(name) or "").strip().lower()
    if not value:
        return f"default:{default}"
    if value in allowed:
        return value
    return "invalid"


def _safe_bool(env: dict[str, str], name: str, *, default: bool) -> str:
    value, valid, _detail = _env_bool(name, env, default=default)
    if not valid:
        return "invalid"
    if not (env.get(name) or "").strip():
        return f"default:{str(default).lower()}"
    return str(value).lower()


def _git_metadata() -> dict[str, Any]:
    metadata: dict[str, Any] = {"head": "unknown", "branch": "unknown", "dirty": "unknown"}
    head = _git_output("rev-parse", "HEAD")
    if head:
        metadata["head"] = head
    branch = _git_output("rev-parse", "--abbrev-ref", "HEAD")
    if branch:
        metadata["branch"] = branch
    status = _git_output("status", "--porcelain")
    if status is not None:
        metadata["dirty"] = bool(status.strip())
    return metadata


def _git_output(*args: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=REPO_ROOT,
            text=True,
            capture_output=True,
            check=False,
            timeout=20,
        )
    except Exception:
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def _print_text(checks: list[CheckResult]) -> None:
    icons = {"ok": "[OK]", "warning": "[WARN]", "error": "[ERR]"}
    print("AWX/IBK readiness check")
    print("=" * 24)
    for check in checks:
        print(f"{icons.get(check.status, '[?]')} {check.name}: {check.detail}")


if __name__ == "__main__":
    raise SystemExit(main())
