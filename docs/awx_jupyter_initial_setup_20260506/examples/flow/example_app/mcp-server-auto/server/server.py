"""
MCP Server - Calculator Tools

FastMCP 기반 MCP 서버로 계산 도구 제공
A2A Server의 Calculator Agent가 이 서버의 도구를 호출

TODO
- Opentelemetry 설정 추가
"""

import logging
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from awx.observability.instrumentation.fastapi import instrument_app
from fastapi import FastAPI
from fastmcp import FastMCP

# ============================================================
# 환경 변수 및 로깅 설정
# ============================================================
load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler()],
)
logger = logging.getLogger("mcp-calculator-server")
SERVICE_NAME = "mcp-server-auto.server"


# ============================================================
# FastMCP 인스턴스 생성
# ============================================================
mcp = FastMCP(SERVICE_NAME)

# FastMCP HTTP App 생성
# path='/'로 설정하면 mount("/mcp")와 결합하여 최종 경로가 /mcp가 됨
mcp_app = mcp.http_app(path="/")


# ============================================================
# FastAPI Lifespan (Combined with FastMCP)
# ============================================================
@asynccontextmanager
async def combined_lifespan(app: FastAPI):
    """
    FastAPI와 FastMCP의 lifespan을 결합
    FastMCP 세션 매니저 초기화를 위해 mcp_app.lifespan 실행이 필수
    """
    logger.info("=== MCP Calculator Server Starting ===")
    logger.info("MCP Streamable HTTP endpoint: /mcp")
    logger.info("Available tools: add, subtract, multiply, divide")
    logger.info("========================================")

    # FastMCP lifespan 실행 (세션 매니저 초기화)
    async with mcp_app.lifespan(app):
        yield

    logger.info("=== MCP Calculator Server Shutting Down ===")


# ============================================================
# FastAPI App 생성
# ============================================================
app = FastAPI(
    title="MCP Calculator Server",
    description="""
## MCP Calculator Server (FastMCP)

계산 도구를 제공하는 MCP 서버입니다.

### 제공 도구
- `add(a, b)`: 두 수를 더합니다
- `subtract(a, b)`: 두 수를 뺍니다
- `multiply(a, b)`: 두 수를 곱합니다
- `divide(a, b)`: 두 수를 나눕니다

### MCP 엔드포인트
- `/mcp`: Streamable HTTP 엔드포인트 (MCP 클라이언트용)
    """,
    version="0.0.1",
    lifespan=combined_lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)
instrument_app(app)

# FastMCP 앱 마운트
app.mount("/mcp", mcp_app)
logger.info("FastMCP mounted at /mcp (Streamable HTTP transport)")


# ============================================================
# 일반 엔드포인트
# ============================================================
@app.get("/")
async def root():
    """루트 엔드포인트 - 서버 정보"""
    return {
        "message": "MCP Calculator Server (FastMCP)",
        "transport": "Streamable HTTP",
        "endpoints": {
            "health": "/health",
            "docs": "/docs",
            "mcp": "/mcp",
        },
        "tools": ["add", "subtract", "multiply", "divide"],
        "usage": {
            "mcp_inspector": "URL: http://localhost:8001/mcp, Transport: Streamable HTTP",
            "fastmcp_client": "StreamableHttpTransport(url='http://localhost:8001/mcp')",
        },
    }


@app.get("/health")
async def health():
    """헬스 체크 엔드포인트"""
    return {"status": "ok", "service": SERVICE_NAME}


# ============================================================
# 테스트 엔드포인트 (MCP 도구 직접 호출)
# ============================================================
@app.get("/test/add")
async def test_add(a: float = 10, b: float = 20):
    """add 도구 테스트"""
    result = add(a, b)
    return {"a": a, "b": b, "result": result}


@app.get("/test/subtract")
async def test_subtract(a: float = 20, b: float = 10):
    """subtract 도구 테스트"""
    result = subtract(a, b)
    return {"a": a, "b": b, "result": result}


@app.get("/test/multiply")
async def test_multiply(a: float = 5, b: float = 4):
    """multiply 도구 테스트"""
    result = multiply(a, b)
    return {"a": a, "b": b, "result": result}


@app.get("/test/divide")
async def test_divide(a: float = 20, b: float = 4):
    """divide 도구 테스트"""
    result = divide(a, b)
    return {"a": a, "b": b, "result": result}


# ============================================================
# MCP Tools 정의
# ============================================================
# [참고] 테스트 엔드포인트보다 뒤에 정의해도 됨
# Python은 런타임에 함수를 찾기 때문에, 테스트 엔드포인트가 호출될 때
# 이 함수들이 이미 정의되어 있음

@mcp.tool()
def add(a: float, b: float) -> float:
    """
    두 수를 더합니다.

    Args:
        a: 첫 번째 숫자
        b: 두 번째 숫자

    Returns:
        두 숫자의 합
    """
    logger.info(f"add: {a} + {b}")
    return a + b


@mcp.tool()
def subtract(a: float, b: float) -> float:
    """
    두 수를 뺍니다.

    Args:
        a: 첫 번째 숫자
        b: 두 번째 숫자

    Returns:
        a에서 b를 뺀 값
    """
    logger.info(f"subtract: {a} - {b}")
    return a - b


@mcp.tool()
def multiply(a: float, b: float) -> float:
    """
    두 수를 곱합니다.

    Args:
        a: 첫 번째 숫자
        b: 두 번째 숫자

    Returns:
        두 숫자의 곱
    """
    logger.info(f"multiply: {a} * {b}")
    return a * b


@mcp.tool()
def divide(a: float, b: float) -> float:
    """
    두 수를 나눕니다.

    Args:
        a: 첫 번째 숫자 (피제수)
        b: 두 번째 숫자 (제수)

    Returns:
        a를 b로 나눈 값

    Raises:
        ValueError: b가 0일 경우
    """
    logger.info(f"divide: {a} / {b}")
    if b == 0:
        raise ValueError("0으로 나눌 수 없습니다")
    return a / b


# ============================================================
# 서버 실행
# ============================================================
if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8001)
