"""Phase 9 tests for the concrete AWX MCP adapter."""

from __future__ import annotations

import pytest
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage

from src.agents.context import BankingContext
from src.agents.tool_calling.awx_mcp import (
    build_awx_mcp_external_tools,
    parse_awx_mcp_allowlist,
)
from src.agents.tool_calling.external import ExternalToolConfigError
from src.agents.tool_calling.runner import run_langchain_tool_agent


class ToolCallingFakeModel(FakeMessagesListChatModel):
    """Fake chat model that supports LangChain agent tool binding."""

    def bind_tools(self, tools, *, tool_choice=None, **kwargs):
        return self


class FakeMcpResource:
    def __init__(self, servers):
        self.servers = servers

    def get(self):
        return self.servers


class FakeMcpServer:
    def __init__(self, *, server_id="svc-1", name="banking-mcp", client=None):
        self.id = server_id
        self.name = name
        self.endpoint = "http://127.0.0.1:8001/mcp"
        self._client = client or FakeMcpClient()

    def get_client(self):
        return self._client


class FakeMcpClient:
    def __init__(self):
        self.calls = []
        self.session = type("Session", (), {"headers": {}})()

    def list_tools(self):
        return [
            {
                "name": "awx_lookup_balance",
                "description": "Read a masked balance from AWX MCP.",
                "inputSchema": {
                    "type": "object",
                    "properties": {"account_hint": {"type": "string", "description": "masked account hint"}},
                    "required": ["account_hint"],
                },
            },
            {
                "name": "awx_execute_transfer",
                "description": "Dangerous tool that should not be allowlisted.",
                "inputSchema": {"type": "object", "properties": {}, "required": []},
            },
        ]

    def call_tool(self, name=None, arguments=None):
        self.calls.append({"name": name, "arguments": arguments})
        return {
            "kind": "mcp_balance",
            "text": "MCP balance lookup complete.",
            "data": {
                "account_number": "111-222-3333",
                "available_amount": 123_000,
                "service_token": "Bearer abcdefghijklmnop",
            },
            "source_agent": "awx_mcp",
        }


def _ctx(**overrides) -> BankingContext:
    values = {
        "user_id": 1,
        "session_id": "tool-phase9",
        "llm_provider": "openai",
        "openai_api_key": "sk-test",
        "tool_calling_enabled": True,
        "tool_calling_awx_mcp_enabled": True,
        "tool_calling_awx_mcp_allowlist": '{"awx_lookup_balance": "read"}',
        "openai_tool_model": "gpt-test",
    }
    values.update(overrides)
    return BankingContext(**values)


def test_phase9_parse_awx_mcp_allowlist_supports_json_and_csv():
    assert parse_awx_mcp_allowlist('{"tool_a": "read", "tool_b": {"side_effect": "prepare"}}') == {
        "tool_a": "read",
        "tool_b": "prepare",
    }
    assert parse_awx_mcp_allowlist("tool_a:read, server.tool_b:prepare") == {
        "tool_a": "read",
        "server.tool_b": "prepare",
    }


def test_phase9_parse_awx_mcp_allowlist_rejects_execute():
    with pytest.raises(ExternalToolConfigError):
        parse_awx_mcp_allowlist('{"awx_execute_transfer": "execute"}')


def test_phase9_awx_mcp_discovery_wraps_allowlisted_tools_only():
    client = FakeMcpClient()
    server = FakeMcpServer(client=client)

    tools = build_awx_mcp_external_tools(_ctx(), mcp_resource=FakeMcpResource([server]))

    assert [tool.name for tool in tools] == ["awx_lookup_balance"]
    assert tools[0].side_effect == "read"
    assert tools[0].parameters["additionalProperties"] is False
    assert client.session.headers["Accept"] == "application/json"


def test_phase9_awx_mcp_discovery_supports_server_prefixed_allowlist():
    client = FakeMcpClient()
    target = FakeMcpServer(server_id="svc-target", name="target-mcp", client=client)
    other = FakeMcpServer(server_id="svc-other", name="other-mcp", client=FakeMcpClient())
    ctx = _ctx(
        awx_mcp_server_name="target-mcp",
        tool_calling_awx_mcp_allowlist="target-mcp.awx_lookup_balance:read",
    )

    tools = build_awx_mcp_external_tools(ctx, mcp_resource=FakeMcpResource([other, target]))

    assert [tool.name for tool in tools] == ["awx_lookup_balance"]


def test_phase9_awx_mcp_tool_runs_through_langchain_policy_and_audit():
    client = FakeMcpClient()
    tools = build_awx_mcp_external_tools(
        _ctx(),
        mcp_resource=FakeMcpResource([FakeMcpServer(client=client)]),
    )
    model = ToolCallingFakeModel(
        responses=[
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "awx_lookup_balance",
                        "args": {"account_hint": "111-222-3333"},
                        "id": "call-awx-mcp",
                    }
                ],
            ),
            AIMessage(content="MCP 조회 결과입니다."),
        ]
    )

    update = run_langchain_tool_agent(
        _ctx(),
        {"user_id": 1, "session_id": "tool-phase9", "current_message": "MCP 잔액 조회"},
        llm=model,
        external_tools=tools,
    )

    audit = update["agent_results"][0]["data"]["tool_audit_events"][0]
    assert client.calls == [{"name": "awx_lookup_balance", "arguments": {"account_hint": "111-222-3333"}}]
    assert audit["tool_name"] == "awx_lookup_balance"
    assert audit["status"] == "completed"
    assert audit["arguments"]["account_hint"] == "****-3333"
    assert audit["result"]["data"]["account_number"] == "****-3333"
    assert audit["result"]["data"]["service_token"] == "***"
    assert audit["result"]["data"]["external_tool"]["source"].startswith("awx_mcp:")


def test_phase9_awx_mcp_disabled_does_not_touch_factory():
    def _raise_if_called():
        raise AssertionError("factory should not be called")

    tools = build_awx_mcp_external_tools(
        _ctx(tool_calling_awx_mcp_enabled=False),
        mcp_resource_factory=_raise_if_called,
    )

    assert tools == []
