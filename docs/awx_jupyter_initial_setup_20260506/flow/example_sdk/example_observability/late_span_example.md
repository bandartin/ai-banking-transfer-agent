# OTel Late Span Example

이 예제는 `trace id`와 `root span id`를 저장해 두었다가, 나중 요청에서 같은 trace에 새 child span을 추가하는 패턴을 보여줍니다.

## 이 예제를 먼저 볼 때

- OpenTelemetry trace continuity 패턴이 필요할 때
- 기존 trace에 later child span을 붙이는 최소 흐름을 보고 싶을 때
- 완성 앱보다 observability 기법 자체를 먼저 이해하고 싶을 때

핵심은 이겁니다.

- 첫 요청에서 root span 생성
- `trace id`와 `root span id` 저장
- 나중 요청에서 저장된 ID로 parent context 복원
- 새 child span을 같은 trace에 late span으로 추가

이 방식은 이미 끝난 span을 수정하는 게 아니라, 나중에 새 span을 덧붙이는 방식입니다.

## API Shape

- `POST /trace/start`
- `POST /trace/add-span`
- `GET /trace/state/{session_id}`

## Example Flow

### 1. Start and store the trace id

```bash
curl -X POST http://127.0.0.1:8001/trace/start \
  -H 'Content-Type: application/json' \
  -d '{
    "session_id": "late-span-demo-1",
    "label": "first request"
  }'
```

### 2. Add a late span later

```bash
curl -X POST http://127.0.0.1:8001/trace/add-span \
  -H 'Content-Type: application/json' \
  -d '{
    "session_id": "late-span-demo-1",
    "label": "human approved later"
  }'
```

### 3. Check stored state

```bash
curl http://127.0.0.1:8001/trace/state/late-span-demo-1
```

## What To Notice

- `trace_id`는 유지되고 새 `span_id`만 바뀝니다.
- linked parent는 처음 저장한 `root span id`입니다.
- 이 패턴은 AWX SDK resource 조회 예제가 아니라 observability 활용 예제입니다.

## Files

- `late_span_example.py`: trace id 저장과 late span 추가 API
- `telemetry_example.py`: 기본 trace/span 사용법
