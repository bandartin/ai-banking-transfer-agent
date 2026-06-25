# langgraph-hitl-auto

이 예제는 LangGraph 기반 질문형 Human-in-the-Loop 채팅 앱입니다. 즉, human in the loop 패턴을 질문/응답 resume 흐름으로 구현한 예제입니다. LLM이 추가 정보가 필요하다고 판단하면 `interrupt()`로 사람 답변을 기다리고, 충분한 정보가 모이면 같은 trace에서 이어서 최종 답변을 생성합니다. 응답 생성은 실제 OpenAI streaming을 사용합니다.

## 이 예제를 먼저 볼 때

- LangGraph 기반 HITL 예제가 필요할 때
- 질문, 대기, `resume`을 같은 trace로 잇는 패턴을 보고 싶을 때
- 단순 tool-calling보다 사람 개입이 포함된 agent UX를 확인하고 싶을 때

## What This Example Shows

- `langgraph.types.interrupt()` + `Command(resume=...)`
- `POST /chat/send`
- `GET /chat/state/{session_id}`
- Gradio chat UI
- OpenAI streaming + 질문형 HITL + same-trace resume
- 응답 중 `steer` 입력 시 현재 generation 중단 후 새 입력으로 이어가기
- reasoning summary 표시
- 파일 첨부를 prompt context로 주입
- 모델 선택 dropdown
- `opentelemetry-instrument` 기반 자동 계측
- 수동 trace context 저장/복원으로 HITL cycle만 같은 trace 유지

핵심은 LangGraph가 질문/대기/재개를 담당하고, OTel trace 연결은 앱 코드가 세션 단위 `traceparent` 저장/복원으로 보강한다는 점입니다.

## Run

```bash
cd /home/user/idea-project/container-script/example_awx/flow
make init app=langgraph-hitl-auto
make sync
make run
```

또는 앱 디렉터리에서 직접:

```bash
cd /home/user/idea-project/container-script/example_awx/flow/example_app/langgraph-hitl-auto
bash run_app.sh
```

`.env` 또는 셸 환경 변수에 최소한 아래 값이 있어야 합니다.

```bash
OPENAI_API_KEY=your-openai-api-key
OPENAI_MODEL=gpt-4o-mini
OPENAI_MODELS=gpt-4o-mini,gpt-4.1-mini,o4-mini
CHAT_MEMORY_TURNS=3
OTEL_TRACES_EXPORTER=otlp
OTEL_METRICS_EXPORTER=otlp
OTEL_LOGS_EXPORTER=otlp
OTEL_EXPORTER_OTLP_PROTOCOL=grpc
OTEL_EXPORTER_OTLP_INSECURE=true
```

`CHAT_MEMORY_TURNS`는 in-memory로 유지할 최근 멀티턴 개수입니다. 기본값은 `3`이고, 최근 user/assistant turn window만 다음 OpenAI 요청에 포함합니다.
`OPENAI_MODELS`는 UI dropdown에 노출할 모델 목록입니다. 비우면 `OPENAI_MODEL`만 사용합니다.
분석환경에서는 `OTEL_EXPORTER_OTLP_*`를 비워 두면 SDK가 collector endpoint를 자동 감지합니다. custom collector override가 필요할 때만 값을 직접 설정하세요.

자동 계측 대상:
- FastAPI / ASGI request span
- 내부 `httpx` 호출
- OpenAI SDK 호출

즉 프로세스는 `opentelemetry-instrument`로 기동하고, 앱 코드는 HITL resume 시 같은 trace를 이어야 하는 지점만 수동 span/context propagation으로 보강합니다.

## 실제 구동 환경과 로컬 차이

- 실제 구동 기준은 builder/inference runtime이며, collector endpoint와 runtime metadata는 플랫폼이 주입합니다.
- 지금 저장소에서 확인하는 로컬 실행은 `make init`, `make run`, UI/API 기동, HITL 상태 전이와 same-trace resume 동작 확인 범위입니다.
- 로컬에서 실제 OpenAI 응답까지 보려면 유효한 `OPENAI_API_KEY`와 사용할 모델 목록이 필요합니다.
- 실제 환경 변수가 필요하면 저장소 값에 기대하지 말고 사용자/운영자에게 요청하세요.

## Chat-like APIs

### Browser Chat UI

브라우저에서 바로 보려면 아래 경로를 열면 됩니다.

```text
http://127.0.0.1:8001/chat/ui
```

이 화면은:

- Gradio 기반 chat UI
- idle 상태에서는 polling을 멈추고, 실제 생성 중일 때만 갱신
- Assistant 질문과 최종 답변을 bubble로 표시
- 질문 단계가 끝나면 `awaiting_human` 상태와 선택지를 표시
- 선택지가 있으면 버튼으로 고르고, `기타`일 때만 직접 입력 가능
- 같은 세션에서 사람 답변을 보내면 same-trace resume
- 응답 중 새 메시지를 보내면 current final-answer stream을 중단하고 steer 처리
- reasoning summary, current trace id, HITL count, steer count 표시
- 모델 선택 dropdown
- 파일 첨부 upload
- 최근 멀티턴 메모리는 `CHAT_MEMORY_TURNS`로 제어

Swagger보다 실제 채팅 UX에 가깝게 HITL 흐름을 보기 위한 Gradio UI입니다. 상단 챗봇 툴바는 `copy_all`만 남기고, 동작하지 않는 share/delete 버튼은 제거했습니다.

### 1. Send the first request

```bash
curl -X POST http://127.0.0.1:8001/chat/send \
  -H 'Content-Type: application/json' \
  -d '{
    "session_id":"chat-session-1",
    "message":"HITL 앱 기획안을 작성해줘",
    "model":"gpt-4o-mini",
    "attachments":[]
  }'
```

응답 예:

```json
{
  "status": "running",
  "session_id": "chat-session-1",
  "run_id": "d8b4...",
  "trace_id": "3f4c...",
  "otel": {
    "same_trace": false
  }
}
```

첫 호출의 결과는 두 가지 중 하나입니다.

- LLM이 정보가 더 필요하다고 판단하면 질문을 만들고 `awaiting_human`
- 충분하다고 판단하면 바로 `completed`

### 2. Check the waiting state

```bash
curl http://127.0.0.1:8001/chat/state/chat-session-1
```

응답 예:

```json
{
  "status": "awaiting_human",
  "session_id": "chat-session-1",
  "trace_id": "3f4c...",
  "pending_question": "어떤 기능을 포함한 HITL 앱을 원하십니까?",
  "pending_options": ["실시간 인간 피드백", "데이터 수집", "사용자 피드백", "기타"],
  "reasoning_summary": "요청이 넓어서 우선 요구 기능을 좁힐 필요가 있습니다.",
  "human_loop_count": 1,
  "steer_count": 0,
  "messages": [
    {"role": "user", "content": "HITL 앱 기획안을 작성해줘"},
    {"role": "assistant", "content": "어떤 기능을 포함한 HITL 앱을 원하십니까?"}
  ]
}
```

### 3. Resume with the same session

```bash
curl -X POST http://127.0.0.1:8001/chat/send \
  -H 'Content-Type: application/json' \
  -d '{
    "session_id":"chat-session-1",
    "message":"실시간 인간 피드백과 파일 첨부가 필요해"
  }'
```

이 두 번째 요청은 새 작업이 아니라 HITL resume 입니다.

그래서:

- `interrupt()`가 멈춘 지점에서 `Command(resume=...)`로 재개
- 사람 답변을 그래프 상태에 반영
- 같은 trace에서 질문을 더 하거나 최종 답변으로 진행

### 4. Check the completed state

```bash
curl http://127.0.0.1:8001/chat/state/chat-session-1
```

응답 예:

```json
{
  "status": "completed",
  "session_id": "chat-session-1",
  "trace_id": "3f4c...",
  "active_run": null,
  "pending_question": null,
  "human_loop_count": 2,
  "steer_count": 1,
  "reasoning_summary": "필수 요구사항이 확보되어 바로 제안서를 작성할 수 있습니다.",
  "messages": [
    {"role": "user", "content": "HITL 앱 기획안을 작성해줘"},
    {"role": "assistant", "content": "어떤 기능을 포함한 HITL 앱을 원하십니까?"},
    {"role": "user", "content": "실시간 인간 피드백과 파일 첨부가 필요해"},
    {"role": "assistant", "content": "주요 사용자는 누구입니까?"},
    {"role": "user", "content": "운영팀이야"},
    {"role": "assistant", "content": "최종 기획안 ..."}
  ]
}
```

핵심은 같은 HITL cycle 안에서만 `first trace_id == resume trace_id`가 되도록 `traceparent`를 세션에 저장했다가, 사람 답변 시 parent context로 복원하는 점입니다.

### 5. Steer while final answer is streaming

최종 답변 생성 중에 같은 세션으로 새 메시지를 보내면 현재 final-answer generation을 중단하고 새 입력으로 이어갑니다.

```bash
curl -X POST http://127.0.0.1:8001/chat/send \
  -H 'Content-Type: application/json' \
  -d '{
    "session_id":"chat-session-1",
    "message":"좀 더 기술 문서 스타일로 바꿔줘"
  }'
```

이때:

- 기존 partial assistant 응답은 메시지 히스토리에 남음
- `steer_count`가 증가
- 새 steer 입력은 같은 세션의 다음 turn으로 처리
- HITL cycle이 아니라면 trace는 새로 시작

## Why Same Trace Works Here

이 앱은 `opentelemetry-instrument`로 자동 계측된 HTTP/OpenAI span 위에, 앱 로직용 수동 span을 추가합니다. 그래서:

- 일반적인 새 채팅 입력은 매번 새 HTTP trace로 시작
- 같은 `session_id`라도 이전 HITL cycle이 끝났으면 다음 작업은 새 trace
- 오직 Assistant 질문 후 `awaiting_human` 상태에서 사람 답변으로 resume 하는 경우만 기존 trace context를 parent로 복원
- 그 결과 HITL 한 사이클 안에서만 같은 trace로 묶입니다

LangGraph 자체가 OTel trace를 자동으로 이어주지는 않습니다. same-trace resume은 이 예제에서 수동 trace propagation으로 구현한 동작입니다.

## Files

- `main.py`: FastAPI entrypoint, session manager, LangGraph graph wiring, send/state endpoints
- `chat_prompts.py`: planner/final prompt와 reasoning parser
- `chat_files.py`: 첨부 파일 읽기와 prompt context 생성, 모델 목록 처리
- `chat_ui.py`: Gradio UI, polling 제어, reasoning/steer/model/file components
- `pyproject.toml`: Gradio/OpenAI/OTEL dependencies
- `run_app.sh`: 실행 스크립트
- `.env.example`: OTEL 전송 환경 변수 예시
