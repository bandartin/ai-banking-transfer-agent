import logging
import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from awx.observability.instrumentation.fastapi import instrument_app
from fastapi import FastAPI
from fastmcp import FastMCP
from fastmcp.server.dependencies import get_http_headers
from opentelemetry import trace

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler()],
)
logger = logging.getLogger("mcp-fast-server")
SERVICE_NAME = "awx-builder-mcp-server"

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("=== MCP Server Starting ===")
    logger.info("SERVICE_NAME: %s", SERVICE_NAME)
    logger.info("MCP SSE endpoint will be available at: /mcp/sse")
    logger.info("Server is ready to accept connections")
    yield
    logger.info("=== MCP Server Shutting Down ===")


mcp = FastMCP(SERVICE_NAME)
app = FastAPI(
    title="MCP Fast Server",
    description="MCP Server",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
)
instrument_app(app)


logger.info("Initializing FastMCP with service_name: %s", SERVICE_NAME)
mcp_app = mcp.http_app(path="/sse", transport="sse")
app.mount("/mcp", mcp_app)
logger.info("FastMCP mounted at /mcp/sse")


class NginxBufferingMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        if path.startswith("/mcp"):
            await self.app(scope, receive, send)
            return

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                is_sse = any(
                    h[0].lower() == b"content-type" and b"text/event-stream" in h[1].lower()
                    for h in headers
                )
                if is_sse:
                    headers.append((b"x-accel-buffering", b"no"))
                    headers.append((b"cache-control", b"no-cache, no-transform"))
                    message["headers"] = headers
            await send(message)

        await self.app(scope, receive, send_wrapper)


app.add_middleware(NginxBufferingMiddleware)


@app.get("/")
async def root():
    return {
        "message": "MCP Fast Server",
        "service_name": SERVICE_NAME,
        "endpoints": {
            "health": "/health",
            "docs": "/docs",
            "mcp_sse": "/mcp/sse",
        },
    }


@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "service_name": SERVICE_NAME,
        "ready": True,
    }


def _attach_session_id() -> None:
    headers = get_http_headers()
    session_id = headers.get("x-awx-session-id")
    if session_id:
        span = trace.get_current_span()
        if span:
            span.set_attribute("awx.session.id", session_id)


@mcp.tool()
def add(a: float, b: float) -> float:
    _attach_session_id()
    logger.info("FastMCP calculating %s + %s", a, b)
    return a + b


@mcp.tool()
def subtract(a: float, b: float) -> float:
    _attach_session_id()
    logger.info("FastMCP calculating %s - %s", a, b)
    return a - b


@mcp.tool()
def multiply(a: float, b: float) -> float:
    _attach_session_id()
    logger.info("FastMCP calculating %s * %s", a, b)
    return a * b


@mcp.tool()
def divide(a: float, b: float) -> float | None:
    _attach_session_id()
    logger.info("FastMCP calculating %s / %s", a, b)
    if b == 0:
        return None
    return a / b


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8001)
