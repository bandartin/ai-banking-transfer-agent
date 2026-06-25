from __future__ import annotations

import logging

from awx.observability.instrumentation.fastapi import instrument_app
from dotenv import load_dotenv
from fastapi import FastAPI
from fastmcp import FastMCP


load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler()],
)
logger = logging.getLogger("mcp-agent-sdk-auto.server")

SERVICE_NAME = "mcp-agent-sdk-auto.server"

mcp = FastMCP(SERVICE_NAME)
mcp_app = mcp.http_app(
    path="/mcp",
    transport="streamable-http",
    json_response=True,
    stateless_http=True,
)

app = FastAPI(
    title="MCP Agent SDK Auto Server",
    description="Calculator MCP server example",
    version="0.1.0",
    lifespan=mcp_app.lifespan,
)
app.router.redirect_slashes = False
mcp_app.router.redirect_slashes = False
instrument_app(app)


class _CanonicalMcpPathMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and scope.get("path") == "/mcp/":
            scope = dict(scope)
            scope["path"] = "/mcp"
            if "raw_path" in scope:
                scope["raw_path"] = b"/mcp"
        await self.app(scope, receive, send)


app.add_middleware(_CanonicalMcpPathMiddleware)


@app.get("/")
async def root() -> dict[str, object]:
    return {
        "service_name": SERVICE_NAME,
        "message": "Calculator MCP server",
        "endpoints": {
            "health": "/health",
            "docs": "/docs",
            "mcp": "/mcp",
        },
        "tools": ["add", "subtract", "multiply", "divide"],
    }


@app.get("/health")
async def health_check() -> dict[str, object]:
    return {
        "status": "healthy",
        "service_name": SERVICE_NAME,
        "ready": True,
    }


app.mount("", mcp_app)


@mcp.tool()
def add(a: float, b: float) -> float:
    """Add two numbers and return the sum."""
    logger.info("add: %s + %s", a, b)
    return a + b


@mcp.tool()
def subtract(a: float, b: float) -> float:
    """Subtract the second number from the first number."""
    logger.info("subtract: %s - %s", a, b)
    return a - b


@mcp.tool()
def multiply(a: float, b: float) -> float:
    """Multiply two numbers and return the product."""
    logger.info("multiply: %s * %s", a, b)
    return a * b


@mcp.tool()
def divide(a: float, b: float) -> float:
    """Divide the first number by the second number."""
    logger.info("divide: %s / %s", a, b)
    if b == 0:
        raise ValueError("division by zero is not allowed")
    return a / b
