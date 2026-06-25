# HITL과 Checkpoint 핵심 정리

이 문서는 팀 내 공유용입니다. 발표자료처럼 길게 설명하기보다, 우리가 현재 코드에서 어떤 구조를 쓰고 있고 왜 그렇게 판단했는지 빠르게 맞추기 위한 메모입니다.

주제는 LangGraph의 `interrupt()`, `Command(resume=...)`, `SqliteSaver`, `thread_id`, checkpoint입니다.

---

## 1. 먼저 결론

현재 구현은 사용자의 다음 입력을 단순히 "새 메시지"로만 보지 않습니다.

이체 확인, 금액 되묻기, OTP 입력처럼 사람이 중간에 개입해야 하는 지점에서는 그래프가 `interrupt()`로 멈추고, LangGraph checkpointer가 그 시점의 상태와 다음 실행 위치를 저장합니다.

다음 요청이 들어오면 우리 코드는 같은 `thread_id`로 저장된 checkpoint를 조회합니다. 아직 이어야 할 node가 남아 있으면 새 workflow를 시작하지 않고 `Command(resume=message)`로 멈춘 지점에 사용자의 답을 넣습니다.

핵심은 이것입니다.

```text
사용자 입력을 기억해서 추측하는 구조가 아니라,
그래프 실행 상태를 저장했다가 같은 thread에서 이어가는 구조다.
```

---

## 2. 우리가 직접 관리하는 것과 LangGraph가 관리하는 것

| 구분 | 우리가 관리 | LangGraph가 관리 |
|---|---|---|
| 세션 식별 | `user_id`, `session_id` | `thread_id` 기준 checkpoint timeline |
| 새 요청 여부 판단 | `graph.get_state()` 호출 | 최신 checkpoint 조회 |
| 대기 상태 확인 | `snapshot.next` 확인 | 다음 실행 node/task 계산 |
| 사람 답변 전달 | `Command(resume=message)` | 이전 `interrupt()`의 반환값으로 연결 |
| 상태 저장 방식 | `SqliteSaver` 선택 | StateSnapshot, writes 직렬화 저장 |

여기서 중요한 실무 포인트는, 우리가 `checkpoint_id`를 직접 들고 다니지 않는다는 점입니다.

일반적인 채팅 resume에서는 `thread_id`만 유지하면 됩니다. `checkpoint_id`는 특정 과거 시점으로 돌아가거나 디버깅할 때 의미가 큽니다.

---

## 3. SqliteSaver를 왜 쓰는가

`SqliteSaver`는 LangGraph checkpointer 구현체 중 하나입니다.

Checkpointer는 역할입니다.

```text
"그래프 상태를 저장하고, 나중에 같은 thread에서 다시 꺼낼 수 있어야 한다."
```

Saver는 그 역할을 어떤 저장소에 구현할지의 선택입니다.

| Saver | 저장 위치 | 쓰기 좋은 곳 |
|---|---|---|
| `InMemorySaver` | 프로세스 메모리 | 테스트, 튜토리얼 |
| `SqliteSaver` | SQLite 파일 | 로컬 데모, 단일 서버 |
| `PostgresSaver` | PostgreSQL | 운영, 다중 서버 |

현재 프로젝트는 로컬 데모와 단일 Flask 서버 구조입니다. 그래서 `SqliteSaver`가 적절합니다.

운영 환경에서 서버가 여러 대로 늘어나거나 checkpoint를 중앙에서 관리해야 하면, SQLite보다는 Postgres 계열 checkpointer가 더 자연스럽습니다.

---

## 4. thread_id는 표준 개념이고, 값 구성은 우리 선택

LangGraph에서 checkpointer를 쓰려면 config에 `thread_id`를 넘깁니다.

```python
config = {"configurable": {"thread_id": "some-thread-id"}}
```

이 프로젝트에서는 다음처럼 구성합니다.

```python
config = {"configurable": {"thread_id": f"{user_id}:{session_id}"}}
```

즉 `thread_id`를 쓰는 것은 LangGraph의 표준 패턴이고, `user_id:session_id` 형태는 우리 프로젝트의 설계 선택입니다.

이 선택은 실용적입니다.

1. 사용자별 checkpoint가 섞이지 않습니다.
2. 같은 사용자의 여러 채팅 세션도 분리됩니다.
3. 디버깅할 때 어떤 사용자와 어떤 세션의 흐름인지 추적하기 쉽습니다.

예:

```text
1:session-a -> 1번 사용자의 A 채팅
1:session-b -> 1번 사용자의 B 채팅
2:session-a -> 2번 사용자의 A 채팅
```

---

## 5. checkpoint에는 무엇이 저장되는가

checkpoint는 단순 대화 history가 아닙니다.

대화 history가 "무슨 말을 주고받았는지"라면, checkpoint는 "그래프가 어디까지 실행됐고, 다음에 무엇을 해야 하는지"까지 포함합니다.

대략 이런 정보가 들어갑니다.

| 항목 | 의미 |
|---|---|
| State 값 | 금액, 수신자, 후보 목록, 보안 평가, 응답 데이터 |
| 다음 실행 위치 | interrupt 이후 이어갈 node/task |
| channel version | 각 state key의 변경 버전 |
| writes | node/task가 만든 중간 state update |
| metadata | checkpoint step, source 등 실행 메타정보 |

그래서 `Command(resume=...)`가 가능한 것입니다.

단순히 `"확인"`이라는 문자열만 보면 무슨 확인인지 알 수 없습니다. 하지만 checkpoint가 있으면 이 `"확인"`이 방금 전 confirm interrupt의 답변이라는 것을 그래프가 알 수 있습니다.

---

## 6. State는 어디에 저장되는가

현재 개발 설정에서는 SQLite 파일에 저장됩니다.

```python
CHECKPOINT_DB_PATH = os.getenv("CHECKPOINT_DB_PATH", "banking_checkpoints.db")
```

SQLite는 상황에 따라 다음 파일들을 함께 만들 수 있습니다.

```text
banking_checkpoints.db
banking_checkpoints.db-wal
banking_checkpoints.db-shm
```

테스트에서는 다릅니다.

```python
CHECKPOINT_DB_PATH = ":memory:"
```

테스트는 메모리 SQLite를 쓰므로 프로세스가 끝나면 checkpoint도 사라집니다.

중요한 점:

```text
Flask session에 State를 저장하는 것 아님
브라우저 localStorage에 저장하는 것 아님
우리가 직접 JSON 파일로 저장하는 것 아님
LangGraph checkpointer가 SQLite에 직렬화해서 저장함
```

---

## 7. 현재 코드의 핵심 흐름

그래프는 checkpointer와 함께 컴파일됩니다.

```python
_conn = sqlite3.connect(checkpoint_path, check_same_thread=False)
_graph = build_banking_graph(checkpointer=SqliteSaver(_conn))
```

요청마다 같은 방식으로 `thread_id`를 구성합니다.

```python
config = {"configurable": {"thread_id": f"{user_id}:{session_id}"}}
```

다음 요청이 들어오면 먼저 저장된 graph state를 봅니다.

```python
snapshot = graph.get_state(config)
has_pending = bool(snapshot.next)
```

pending node가 있으면 resume합니다.

```python
if has_pending:
    graph_input = Command(resume=message)
else:
    graph_input = fresh_turn_state(user_id, session_id, message)
```

이 구조 때문에 확인 대기 중 사용자가 `"확인"`이라고 말하면 새 이체 요청으로 해석하지 않고, 이전 `interrupt()`의 답변으로 들어갑니다.

---

## 8. graph.get_state()를 어떻게 이해하면 좋은가

`graph.get_state(config)`는 현재 Python 변수에서 dict 하나를 꺼내는 함수가 아닙니다.

주어진 `thread_id`를 기준으로 checkpointer에서 최신 checkpoint를 조회하고, 그 결과를 `StateSnapshot`으로 돌려줍니다.

이 프로젝트에서 우리가 보는 핵심은 `snapshot.next`입니다.

```text
snapshot.next가 비어 있음 -> 끝난 그래프. 새 턴 시작.
snapshot.next가 있음     -> 중간에 멈춘 그래프. resume 필요.
```

여기서 `pending_state`와 혼동하면 안 됩니다.

`pending_state`는 UI와 로그를 위한 표현입니다. 실제 resume 판단은 `snapshot.next`로 합니다.

---

## 9. 이전 node를 왜 다시 안 밟는가

LangGraph는 checkpoint에 State 값뿐 아니라 실행 위치와 version 정보를 저장합니다.

그래서 같은 `thread_id`로 resume하면 `START -> plan -> transfer -> validate`를 매번 다시 타지 않고, pending interrupt 기준으로 이어갑니다.

다만 한 가지 조심해야 합니다.

`interrupt()`가 들어 있는 node는 resume 때 다시 진입할 수 있습니다. 다만 `interrupt()` 호출이 resume 값을 반환하므로, 코드 흐름상 interrupt 이후 로직으로 자연스럽게 이어집니다.

이 말의 실무적 의미는 중요합니다.

```text
interrupt() 이전에는 외부 부작용을 두지 않는 것이 안전하다.
```

우리 코드에서 실제 이체 실행을 `confirm_node` 앞에 두지 않고, 확인과 OTP 이후 `execute_node`에 둔 이유도 여기에 있습니다.

---

## 10. 확인 대기 중 새 요청은 어떻게 처리하는가

확인 카드가 떠 있는 상태에서 사용자가 `"잔고 얼마야?"`라고 물을 수 있습니다.

이 입력을 무조건 확인 카드의 답변으로 처리하면 UX가 어색하고, 금융 업무에서는 위험할 수 있습니다.

그래서 `confirm_node`는 입력을 분류합니다.

| 입력 | 처리 |
|---|---|
| `"확인"` | `execute` 또는 `otp`로 진행 |
| `"취소"` | 이체 취소 |
| `"아니 3만원으로"` | 금액 수정 후 재검증 |
| `"잔고 얼마야?"` | 부모 Supervisor의 `plan`으로 handoff |

핵심은 `Command(graph=Command.PARENT, goto="plan")`입니다.

서브그래프인 TransferAgent가 "이건 이체 확인 답변이 아니라 새 요청"이라고 판단하면 부모 Supervisor에게 다시 planning을 맡깁니다.

---

## 11. 우리가 얻는 장점

이 구조의 장점은 꽤 명확합니다.

1. 수동 상태 머신이 줄어듭니다.
2. 확인, OTP, 금액 되묻기 같은 HITL 흐름이 자연스럽습니다.
3. HTTP 요청이 여러 번 나뉘어도 그래프 실행 맥락이 유지됩니다.
4. State와 실행 위치가 함께 저장되므로 디버깅 관점이 좋아집니다.
5. 나중에 SQLite에서 Postgres로 옮겨도 개념은 유지됩니다.

제가 좋게 보는 지점은, 이 구조가 "AI가 기억하는 척하는 방식"이 아니라는 점입니다.

업무 시스템 관점에서는 추측보다 복원이 낫습니다.  
이 구현은 대화 맥락을 LLM에게 다시 설명해서 이어가는 방식이 아니라, workflow의 실제 실행 지점을 저장하고 복원합니다.

---

## 12. 조심할 점

좋은 구조지만 무조건 공짜는 아닙니다.

1. 같은 대화를 이어가려면 같은 `session_id`가 유지되어야 합니다.
2. Context는 checkpoint에 저장되지 않으므로 resume 때도 다시 주입해야 합니다.
3. `interrupt()` 이전에 외부 부작용을 두면 resume 시 재실행 위험을 고려해야 합니다.
4. SQLite는 단일 서버 데모에는 좋지만, 운영 다중 서버 구조에는 한계가 있습니다.
5. 오래된 checkpoint를 언제 지울지 lifecycle 정책이 필요합니다.

현재 `/api/chat/reset`은 기존 checkpoint row를 직접 삭제하기보다 새 `session_id`를 발급해서 새 thread를 시작하는 방식입니다.

운영 수준으로 가려면 `delete_thread`, 보존 기간, 사용자별 checkpoint 정리 정책을 따로 잡는 것이 좋습니다.

---

## 13. 팀에서 합의하면 좋은 기준

앞으로 이 구조를 확장할 때는 다음 기준을 맞추는 것이 좋겠습니다.

### State에 넣을 것

그래프 진행 중 바뀌고, checkpoint에 저장되어야 하는 값입니다.

예:

- 수신자 alias
- 금액
- 후보 수신자 목록
- 보안 평가 결과
- pending transfer data
- 최종 response data

### Context에 넣을 것

이번 invoke 동안 고정된 실행 환경입니다. checkpoint에 저장하지 않습니다.

예:

- 사용자 등급
- 나이
- risk profile
- LLM provider
- OTP 기준 금액
- demo OTP code

### DB domain table에 넣을 것

그래프 상태가 아니라 비즈니스 데이터입니다.

예:

- 계좌
- 수신자
- 이체 내역
- 즐겨찾기
- 학습된 alias

이 셋을 섞지 않는 것이 중요합니다.

---

## 14. 한 문장으로 설명하면

> 우리 HITL 구조는 `thread_id`로 같은 대화 timeline을 찾고, `SqliteSaver`가 저장한 checkpoint에서 State와 다음 실행 위치를 복원한 뒤, `Command(resume=...)`로 이전 `interrupt()` 지점에 사용자 답변을 넣어 workflow를 이어가는 방식입니다.

---

## 15. 코드에서 볼 위치

| 내용 | 파일 |
|---|---|
| checkpointer 연결 | `src/agents/supervisor/graph.py` |
| `thread_id` 구성 | `src/agents/supervisor/graph.py` |
| `graph.get_state()`와 `snapshot.next` | `src/agents/supervisor/graph.py` |
| `Command(resume=...)` | `src/agents/supervisor/graph.py` |
| State schema와 reducer | `src/agents/state.py` |
| 확인, 금액, OTP interrupt | `src/agents/subagents/transfer.py` |
| 부모 Supervisor handoff | `src/agents/subagents/transfer.py` |
| 테스트용 memory checkpoint | `tests/conftest.py` |
| 기본 checkpoint DB path | `config.py` |

---

## 16. 참고 자료

- LangGraph Persistence: https://docs.langchain.com/oss/python/langgraph/persistence
- LangGraph Interrupts: https://docs.langchain.com/oss/python/langgraph/interrupts
- LangGraph Checkpointers Reference: https://reference.langchain.com/python/langgraph/checkpoints
- LangGraph SQLite Checkpointer Source: https://github.com/langchain-ai/langgraph/blob/main/libs/checkpoint-sqlite/langgraph/checkpoint/sqlite/__init__.py
