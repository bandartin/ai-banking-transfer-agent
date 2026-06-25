"""AWX MCP discovery adapter for model-callable external tools."""

from __future__ import annotations

import json
from typing import Any, Callable, Iterable

from src.agents.tool_calling.external import (
    ExternalToolConfigError,
    ExternalToolSpec,
    external_tool_to_agent_tool,
)
from src.agents.tool_calling.registry import AgentTool, ToolRuntime
from src.awx_runtime.observability import manual_span


McpResourceFactory = Callable[[], Any]
_ALLOWED_AWX_MCP_SIDE_EFFECTS = {"read", "prepare"}


class AwxMcpDiscoveryError(RuntimeError):
    """Raised when AWX MCP discovery is enabled but cannot be safely configured."""


def build_awx_mcp_external_tools(
    ctx: Any,
    *,
    mcp_resource: Any | None = None,
    mcp_resource_factory: McpResourceFactory | None = None,
) -> list[AgentTool]:
    """Discover allowlisted AWX MCP tools and wrap them as local AgentTool objects."""
    if not bool(getattr(ctx, "tool_calling_awx_mcp_enabled", False)):
        return []

    allowlist = parse_awx_mcp_allowlist(str(getattr(ctx, "tool_calling_awx_mcp_allowlist", "") or ""))
    if not allowlist:
        return []

    resource = mcp_resource or _build_mcp_resource(mcp_resource_factory)
    if resource is None:
        return []

    with manual_span(
        "banking.awx_mcp.discovery",
        {
            "awx_mcp.enabled": True,
            "awx_mcp.allowlist.count": len(allowlist),
        },
    ):
        servers = _discover_servers(resource)
        selected = _select_server(
            servers,
            service_id=str(getattr(ctx, "awx_mcp_service_id", "") or ""),
            server_name=str(getattr(ctx, "awx_mcp_server_name", "") or ""),
        )
    if selected is None:
        return []

    client = _get_client(selected)
    _configure_mcp_client(client)

    tools: list[AgentTool] = []
    with manual_span(
        "banking.awx_mcp.tools.list",
        {
            "awx_mcp.server.id": _server_id(selected),
            "awx_mcp.server.name": _server_name(selected),
        },
    ):
        tool_schemas = list(_iter_tool_schemas(_list_tools(client)))

    for schema in tool_schemas:
        tool_name = str(schema.get("name") or "").strip()
        if not tool_name:
            continue

        side_effect = _side_effect_for_tool(allowlist, selected, tool_name)
        if not side_effect:
            continue

        spec = ExternalToolSpec(
            name=tool_name,
            description=_tool_description(schema, selected),
            parameters=_tool_parameters(schema),
            side_effect=side_effect,
            source=_server_source_label(selected),
        )
        tools.append(external_tool_to_agent_tool(spec, _mcp_caller(client, tool_name)))

    return tools


def parse_awx_mcp_allowlist(raw: str) -> dict[str, str]:
    """Parse a JSON or CSV allowlist mapping MCP tool names to side effects."""
    text = raw.strip()
    if not text:
        return {}

    if text[0] in "[{":
        parsed = _parse_json_allowlist(text)
    else:
        parsed = _parse_csv_allowlist(text)

    normalized: dict[str, str] = {}
    for name, side_effect in parsed.items():
        tool_name = str(name or "").strip()
        effect = str(side_effect or "").strip().lower()
        if not tool_name:
            raise ExternalToolConfigError("AWX MCP allowlist contains an empty tool name.")
        if effect not in _ALLOWED_AWX_MCP_SIDE_EFFECTS:
            raise ExternalToolConfigError(
                f"AWX MCP tool '{tool_name}' has side_effect='{effect}'. "
                "Only read and prepare are allowed."
            )
        normalized[tool_name] = effect
    return normalized


def _parse_json_allowlist(text: str) -> dict[str, str]:
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ExternalToolConfigError(f"AWX MCP allowlist is not valid JSON: {exc}") from exc

    if isinstance(payload, dict):
        parsed: dict[str, str] = {}
        for name, value in payload.items():
            if isinstance(value, str):
                parsed[str(name)] = value
            elif isinstance(value, dict):
                parsed[str(name)] = str(value.get("side_effect") or value.get("sideEffect") or "")
            else:
                raise ExternalToolConfigError(
                    f"AWX MCP allowlist entry for '{name}' must be a side-effect string or object."
                )
        return parsed

    if isinstance(payload, list):
        parsed = {}
        for item in payload:
            if not isinstance(item, dict):
                raise ExternalToolConfigError("AWX MCP allowlist list entries must be objects.")
            parsed[str(item.get("name") or "")] = str(item.get("side_effect") or item.get("sideEffect") or "")
        return parsed

    raise ExternalToolConfigError("AWX MCP allowlist must be a JSON object, JSON list, or CSV string.")


def _parse_csv_allowlist(text: str) -> dict[str, str]:
    parsed: dict[str, str] = {}
    for raw_entry in text.split(","):
        entry = raw_entry.strip()
        if not entry:
            continue
        if ":" not in entry:
            raise ExternalToolConfigError(
                "AWX MCP allowlist CSV entries must use '<tool_name>:<read|prepare>'."
            )
        name, side_effect = entry.split(":", 1)
        parsed[name.strip()] = side_effect.strip()
    return parsed


def _build_mcp_resource(factory: McpResourceFactory | None) -> Any | None:
    if factory is not None:
        return factory()
    try:
        from awx.resources import Mcp
    except Exception:
        return None
    try:
        return Mcp()
    except Exception:
        return None


def _discover_servers(resource: Any) -> list[Any]:
    getter = getattr(resource, "get", None)
    if not callable(getter):
        raise AwxMcpDiscoveryError("AWX MCP resource does not expose get().")
    try:
        servers = getter()
    except Exception as exc:
        raise AwxMcpDiscoveryError(f"AWX MCP discovery failed: {exc}") from exc
    return list(_iter_servers(servers))


def _iter_servers(servers: Any) -> Iterable[Any]:
    if servers is None:
        return []
    if isinstance(servers, dict):
        for key in ("items", "servers", "mcps", "data", "results"):
            items = servers.get(key)
            if isinstance(items, list):
                return items
        return []
    try:
        return list(servers)
    except TypeError:
        return [servers]


def _select_server(servers: list[Any], *, service_id: str, server_name: str) -> Any | None:
    if not servers:
        return None

    if service_id:
        matched = _find_server(servers, lambda item: _server_id(item) == service_id)
        if matched is not None:
            return matched
        raise AwxMcpDiscoveryError(f"Configured AWX MCP service id '{service_id}' was not discovered.")

    if server_name:
        matched = _find_server(
            servers,
            lambda item: _server_name(item) == server_name or _server_id(item) == server_name,
        )
        if matched is not None:
            return matched
        raise AwxMcpDiscoveryError(f"Configured AWX MCP server name '{server_name}' was not discovered.")

    return servers[0]


def _find_server(servers: list[Any], predicate: Callable[[Any], bool]) -> Any | None:
    finder = getattr(servers, "find", None)
    if callable(finder):
        try:
            found = finder(predicate)
            if found is not None:
                return found
        except Exception:
            pass
    for item in servers:
        if predicate(item):
            return item
    return None


def _get_client(server: Any) -> Any:
    get_client = getattr(server, "get_client", None)
    if not callable(get_client):
        raise AwxMcpDiscoveryError("Selected AWX MCP server does not expose get_client().")
    try:
        return get_client()
    except Exception as exc:
        raise AwxMcpDiscoveryError(f"AWX MCP client creation failed: {exc}") from exc


def _configure_mcp_client(client: Any) -> None:
    session = getattr(client, "session", None)
    headers = getattr(session, "headers", None)
    if headers is not None:
        try:
            headers["Accept"] = "application/json"
        except Exception:
            pass


def _list_tools(client: Any) -> Any:
    list_tools = getattr(client, "list_tools", None)
    if not callable(list_tools):
        raise AwxMcpDiscoveryError("Selected AWX MCP client does not expose list_tools().")
    try:
        return list_tools()
    except Exception as exc:
        raise AwxMcpDiscoveryError(f"AWX MCP tool listing failed: {exc}") from exc


def _iter_tool_schemas(payload: Any) -> Iterable[dict[str, Any]]:
    if isinstance(payload, dict):
        for key in ("tools", "items", "data", "results"):
            items = payload.get(key)
            if isinstance(items, list):
                return [item for item in items if isinstance(item, dict)]
        return []
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    return []


def _tool_description(schema: dict[str, Any], server: Any) -> str:
    description = str(schema.get("description") or "").strip()
    if description:
        return description
    return f"AWX MCP tool from {_server_source_label(server)}."


def _tool_parameters(schema: dict[str, Any]) -> dict[str, Any]:
    parameters = (
        schema.get("inputSchema")
        or schema.get("input_schema")
        or schema.get("parameters")
        or {"type": "object", "properties": {}, "required": []}
    )
    if not isinstance(parameters, dict):
        parameters = {"type": "object", "properties": {}, "required": []}
    normalized = dict(parameters)
    normalized.setdefault("type", "object")
    normalized.setdefault("properties", {})
    normalized.setdefault("required", [])
    normalized.setdefault("additionalProperties", False)
    return normalized


def _mcp_caller(client: Any, tool_name: str) -> Callable[[ToolRuntime, dict[str, Any]], Any]:
    def _call(_runtime: ToolRuntime, arguments: dict[str, Any]) -> Any:
        return _call_mcp_tool(client, tool_name, arguments)

    return _call


def _call_mcp_tool(client: Any, tool_name: str, arguments: dict[str, Any]) -> Any:
    call_tool = getattr(client, "call_tool", None)
    if not callable(call_tool):
        raise AwxMcpDiscoveryError("Selected AWX MCP client does not expose call_tool().")
    with manual_span("banking.awx_mcp.tool.call", {"awx_mcp.tool.name": tool_name}):
        try:
            return call_tool(name=tool_name, arguments=arguments)
        except TypeError:
            return call_tool(tool_name, arguments)


def _side_effect_for_tool(allowlist: dict[str, str], server: Any, tool_name: str) -> str:
    for key in (
        tool_name,
        f"{_server_name(server)}.{tool_name}",
        f"{_server_id(server)}.{tool_name}",
    ):
        if key in allowlist:
            return allowlist[key]
    return ""


def _server_source_label(server: Any) -> str:
    name = _server_name(server)
    server_id = _server_id(server)
    if name and server_id:
        return f"awx_mcp:{name}:{server_id}"
    return f"awx_mcp:{name or server_id or 'unknown'}"


def _server_name(server: Any) -> str:
    return str(_server_value(server, "name") or _server_value(server, "serviceName") or "").strip()


def _server_id(server: Any) -> str:
    return str(_server_value(server, "id") or _server_value(server, "serviceId") or "").strip()


def _server_value(server: Any, key: str) -> Any:
    if isinstance(server, dict):
        return server.get(key)
    value = getattr(server, key, None)
    if value:
        return value
    data = getattr(server, "_data", None)
    if isinstance(data, dict):
        return data.get(key)
    return None
