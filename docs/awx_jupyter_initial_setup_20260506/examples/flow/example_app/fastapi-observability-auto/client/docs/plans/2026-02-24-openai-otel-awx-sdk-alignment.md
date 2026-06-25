# OpenAI OTel AWX SDK Alignment Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Restructure the client example to use OpenAI and OpenTelemetry SDK patterns directly while keeping AWX SDK integration natural and easy.

**Architecture:** Replace LangChain-centered LLM internals with an OpenAI SDK adapter layer, keep the public chat endpoint contract stable, and add explicit tracing spans at orchestration boundaries. AWX concerns (session header, credential resolution, MCP transport) remain first-class and are grouped behind small helper abstractions.

**Tech Stack:** FastAPI, OpenAI Python SDK (`AsyncOpenAI`), OpenTelemetry API/SDK, fastmcp, awx-observability SDK, pytest.

---

### Task 1: Lock expected SDK-style behavior with tests

**Files:**
- Modify: `tests/test_llm_service_stream.py`
- Modify: `tests/test_chat_service.py`

**Step 1: Write failing tests for OpenAI adapter paths**
- Add tests that patch OpenAI adapter construction and verify stream/non-stream paths are called with SDK-like message payloads.

**Step 2: Run target tests and verify failures**
- Run: `pytest -q tests/test_llm_service_stream.py tests/test_chat_service.py`
- Expect: FAIL for missing adapter behavior.

### Task 2: Implement OpenAI SDK adapter + OTel spans

**Files:**
- Modify: `llm_service.py`
- Modify: `planner.py`

**Step 1: Implement adapter**
- Add OpenAI `AsyncOpenAI` adapter object with `ainvoke/astream` compatibility methods.
- Preserve existing public helper function names for backward compatibility.

**Step 2: Add tracing boundaries**
- Add explicit OpenTelemetry spans/attributes for planner invocation and LLM generation wrappers.

**Step 3: Run focused tests**
- Run: `pytest -q tests/test_llm_service_stream.py`
- Expect: PASS.

### Task 3: Reshape chat orchestration to SDK-like service surface

**Files:**
- Modify: `chat_service.py`
- Modify: `tests/test_chat_service.py`

**Step 1: Introduce service object**
- Add a `ChatCompletionsService` orchestrator class with a `create()` method (OpenAI-style naming).
- Keep `_execute_chat()` as compatibility wrapper.

**Step 2: Keep AWX integration natural**
- Ensure `X-AWX-Session-Id` propagation and MCP transport usage are encapsulated and easy to patch.

**Step 3: Run focused tests**
- Run: `pytest -q tests/test_chat_service.py`
- Expect: PASS.

### Task 4: Update packaging/deps and run full verification

**Files:**
- Modify: `pyproject.toml`
- Modify: `README.md` (briefly reflect OpenAI SDK-first internals)

**Step 1: Dependency alignment**
- Add direct `openai` dependency and keep compatibility dependencies only if still used.

**Step 2: Run full test suite**
- Run: `pytest -q`
- Expect: PASS.
