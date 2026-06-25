# AWX 플랫폼 배포 및 실행 가이드

> 대상: AI 이체 서비스 `ai-banking-transfer-agent`  
> 정본 유지 원칙: 루트의 현재 코드가 정본이고, AWX용 `flow`는 빌드 산출물이다.  
> 기본 산출물 위치: `dist/awx-flow/`

---

## 1. 전체 흐름 한눈에 보기

AWX에 올릴 때는 현재 저장소 전체를 그대로 `flow/`로 쓰지 않는다. 먼저 정본 소스에서 AWX 실행 산출물을 만든 뒤, 그 산출물을 AWX workspace의 `flow/`로 올린다.

```text
현재 저장소 정본
  app.py / config.py / src / templates / static
        |
        | scripts/build_awx_flow.py
        v
AWX 산출물
  dist/awx-flow/
        |
        | AWX workspace의 flow/로 업로드 또는 직접 생성
        v
AWX 실행
  awx run
        |
        v
AWX 패키징/배포
  awx package --message "..."
```

핵심 파일:

| 파일 | 역할 |
|---|---|
| `awx/run-application.sh` | AWX가 실행하는 진입점. Portal bootstrap, `uv sync`, OTel 계측, Flask 앱 실행을 담당한다. |
| `awx/awx-bootstrap.json` | AWX Portal credential/external resource 사전 준비 manifest. |
| `awx/pyproject.toml` | AWX 런타임에서 설치할 Python 의존성. |
| `scripts/build_awx_flow.py` | 정본 소스를 AWX 산출물로 조립한다. |
| `src/awx_runtime/` | AWX credential, LLMLog, OTel, redaction optional 어댑터. |

---

## 2. 사전 준비

### 2.1 AWX Portal에서 확인할 값

운영자 또는 AWX Portal에서 아래 값을 확인한다.

| 값 | 예시 | 설명 |
|---|---|---|
| Project ID | `PJT...` | 개발 모드에서 resource 조회에 필요할 수 있다. |
| User ID | `1000001` | 개발 모드에서 credential/resource 조회에 필요할 수 있다. |
| Credential service id | `30` | OpenAI LLM credential이 연결된 service id. 현재 manifest 기본값은 예시값 `30`이다. |
| Provider alias | `OpenAI` | AWX credential provider alias. |
| Service type name | `LLM` | AWX credential service type. |
| External resource solution id | `BUILDER` | 외부 리소스 조회용 solution id. |

현재 기본값은 [awx/awx-bootstrap.json](../awx/awx-bootstrap.json)에 들어 있다. 실제 플랫폼 값이 다르면 반드시 바꾼다.

```json
{
  "credentials": [
    {
      "service_id": 30,
      "provider_alias": "OpenAI",
      "service_type_name": "LLM"
    }
  ]
}
```

### 2.2 로컬에서 먼저 확인할 것

로컬 또는 개발 PC에서는 다음을 확인한다.

```bash
uv run python scripts/build_awx_flow.py --clean --include-tests
```

성공하면 아래 디렉토리가 생성된다.

```text
dist/awx-flow/
├── run-application.sh
├── awx-bootstrap.json
├── pyproject.toml
├── app.py
├── config.py
├── seed.py
├── src/
├── static/
├── templates/
└── tests/
```

`dist/`는 git ignore 대상이다. 정본이 아니라 배포 산출물이므로 직접 수정하지 않는다.

---

## 3. AWX Workspace에 올리는 방법

상황에 따라 두 가지 방법 중 하나를 선택한다.

### 방법 A. AWX Workspace 안에서 직접 생성

AWX Jupyter/Code Server 터미널에서 저장소를 받을 수 있다면 이 방법이 가장 깔끔하다.

```bash
cd /project/work
git clone <저장소_URL> ai-banking-transfer-agent
cd ai-banking-transfer-agent

# AWX가 인식할 flow 디렉토리를 workspace 루트에 생성
uv run python scripts/build_awx_flow.py --output ../flow --clean

cd ../flow
ls
```

`../flow` 안에 `run-application.sh`, `app.py`, `src/`가 보이면 준비가 된 것이다.

테스트까지 포함하고 싶으면 다음처럼 실행한다.

```bash
uv run python scripts/build_awx_flow.py --output ../flow --clean --include-tests
```

### 방법 B. 로컬에서 만든 산출물을 업로드

AWX Workspace에서 git clone이 어렵다면 로컬에서 산출물을 만든 뒤 `dist/awx-flow/`의 내용물을 AWX workspace의 `flow/`에 업로드한다.

```bash
uv run python scripts/build_awx_flow.py --clean
```

업로드 후 AWX 터미널에서 확인한다.

```bash
cd /project/work/flow
ls
```

다음 파일들이 보여야 한다.

```text
run-application.sh
awx-bootstrap.json
pyproject.toml
app.py
config.py
src/
templates/
static/
```

---

## 4. 환경 변수 설정

### 4.1 최소 실행

AWX 런타임에서 Portal credential을 사용하려면 다음 값이 맞아야 한다.

```bash
export LLM_PROVIDER=openai
export AWX_CREDENTIAL_SERVICE_ID=30
export AWX_CREDENTIAL_PROVIDER_ALIAS=OpenAI
export AWX_CREDENTIAL_SERVICE_TYPE_NAME=LLM
export AWX_CREDENTIAL_VARIABLE_NAME=OPENAI_API_KEY
export AWX_EXTERNAL_RESOURCE_SOLUTION_ID=BUILDER
```

`AWX_CREDENTIAL_SERVICE_ID=30`은 예시값이다. 실제 Portal credential service id로 바꾼다.

개발 모드에서 AWX SDK가 `MLDL_USER_ID`, `MLDL_PROJ_ID`를 요구하면 다음도 설정한다.

```bash
export MLDL_USER_ID=<AWX 사용자 ID>
export MLDL_PROJ_ID=<AWX 프로젝트 ID>
```

추론/배포 런타임에서는 위 값들이 플랫폼에서 주입될 수 있다. 이미 주입된다면 수동 설정하지 않는다.

### 4.2 포트와 DB 경로

기본 포트는 `8000`이다.

```bash
export FLASK_PORT=8000
```

SQLite DB와 LangGraph checkpoint DB는 쓰기 가능한 임시 영역을 사용한다.

```bash
export DATABASE_URL="sqlite:///${PATH_TEMP:-/tmp}/banking_demo.db"
export CHECKPOINT_DB_PATH="${PATH_TEMP:-/tmp}/banking_checkpoints.db"
```

`run-application.sh`가 위 기본값을 자동으로 잡아 주므로 보통은 별도 설정이 필요 없다.

### 4.3 OTel endpoint

AWX 예제 정책에 따라 `OTEL_EXPORTER_OTLP_*` 값은 직접 하드코딩하지 않는다. 분석/추론 환경에서 AWX SDK가 collector endpoint를 자동 감지하도록 비워 둔다.

직접 collector override가 필요한 경우에만 운영자 지시에 따라 설정한다.

---

## 5. AWX에서 실행하기

AWX flow 디렉토리로 이동한다.

```bash
cd /project/work/flow
```

실행 권한이 없으면 한 번만 부여한다.

```bash
chmod +x run-application.sh
```

### 5.1 AWX CLI로 실행

가장 표준적인 실행 방식이다.

```bash
awx run
```

내부적으로 `run-application.sh`가 실행되고 다음을 수행한다.

1. `awx-bootstrap.json`을 읽어 `bootstrap_portal_runtime(...)` 시도
2. `uv sync --no-install-project --inexact`로 의존성 준비
3. `opentelemetry-instrument python app.py`로 Flask 앱 실행
4. OTel 도구가 없으면 `python app.py`로 폴백

정상 실행 로그 예시:

```text
[AWX] Portal runtime resources bootstrapped.
[AWX] Starting Banking Transfer Agent on 0.0.0.0:8000
[APP] AI Transfer Assistant - http://localhost:8000
```

### 5.2 직접 실행

AWX CLI 없이 스크립트를 바로 확인할 때 사용한다.

```bash
bash run-application.sh
```

---

## 6. 브라우저에서 접속하기

AWX/Jupyter/Code Server 환경에서는 보통 포트 프록시 URL로 접속한다.

예시:

```text
https://<workspace-host>/proxy/8000/chat
```

플랫폼 UI가 포트 열기 버튼을 제공하면 `8000` 포트를 선택한다.

확인할 페이지:

| URL | 확인 내용 |
|---|---|
| `/chat` | 채팅 UI, 사용자 전환, Supervisor 계획 패널 |
| `/agent-logs/` | 로컬 DB 기반 AgentRunLog |
| `/.well-known/agent-card.json` | A2A 대표 Agent Card |
| `/api/a2a/agents` | Sub-Agent 카드 목록 |

간단한 API 확인:

```bash
curl -X POST http://127.0.0.1:8000/api/chat/message \
  -H "Content-Type: application/json" \
  -d '{"message":"잔고 보여줘"}'
```

---

## 7. 기능 스모크 시나리오

브라우저 `/chat`에서 다음 순서로 확인한다.

1. `잔고 보여줘`
   - 잔액 응답이 나와야 한다.
2. `엄마에게 5만원 보내줘`
   - 확인 카드가 나와야 한다.
3. `확인`
   - 성공 응답이 나와야 한다.
4. `민수에게 5만원 보내줘`
   - 동명이인 후보가 나와야 한다.
5. `집주인한테 350만원 보내줘`
   - 확인 후 OTP 단계로 넘어가야 한다.
6. `123456`
   - OTP 성공 후 이체 성공 응답이 나와야 한다.
7. `잔고 보여주고 자주 보내는 사람도 추천해줘`
   - Inquiry와 Recommend가 병렬로 실행되고 합성 응답이 나와야 한다.

로그 확인:

- `/agent-logs/`에서 실행 계획, graph trace, node logs 확인
- AWX Portal observability 화면에서 OTel trace 확인
- AWX LLMLog에서 `slot_extraction`, `supervisor_planning`, `response_polish` 호출 확인

LLM credential이 없으면 LLMLog가 없거나 줄어들 수 있다. 이 경우에도 결정론 파서로 주요 기능은 동작해야 한다.

---

## 8. 패키징 및 배포 요청

실행 확인이 끝나면 같은 `flow` 디렉토리에서 패키징한다.

```bash
cd /project/work/flow
awx package --message "ai-banking-transfer-agent awx migration"
```

성공하면 AWX CLI가 artifact 식별자 또는 배포 요청 결과를 출력한다.

패키징 전 최종 확인:

```bash
pwd
ls
test -f run-application.sh
test -f awx-bootstrap.json
test -f pyproject.toml
test -d src
test -d templates
test -d static
```

패키징 대상에는 `.env`, DB 파일, 로컬 venv, `dist/`, `.git/`이 들어가면 안 된다.

---

## 9. 배포 후 확인

배포 URL이 발급되면 아래 순서로 확인한다.

1. `/chat` 접속
2. 기본 사용자로 `잔고 보여줘` 실행
3. 이체 확인/취소 시나리오 실행
4. `/agent-logs/`에서 로그 조회
5. AWX Portal에서 trace/LLMLog/metering 확인
6. A2A card endpoint 확인

```bash
curl https://<배포_URL>/.well-known/agent-card.json
```

---

## 10. 자주 나는 문제와 대응

### 10.1 `Credential.get` 실패 또는 LLM이 deterministic으로 동작

증상:

- LLM 호출이 되지 않는다.
- 응답은 나오지만 rule-based 경로로만 동작한다.

확인:

```bash
echo $LLM_PROVIDER
echo $AWX_CREDENTIAL_SERVICE_ID
echo $AWX_CREDENTIAL_PROVIDER_ALIAS
echo $AWX_CREDENTIAL_SERVICE_TYPE_NAME
```

대응:

- `LLM_PROVIDER=openai`인지 확인한다.
- `AWX_CREDENTIAL_SERVICE_ID`가 실제 Portal credential service id인지 확인한다.
- 개발 모드라면 `MLDL_USER_ID`, `MLDL_PROJ_ID`가 필요한지 확인한다.
- Portal credential 변수명에 `OPENAI_API_KEY`가 있는지 확인한다.

### 10.2 `ModuleNotFoundError: awx`

로컬에서는 정상이다. AWX SDK가 없으면 optional adapter가 no-op으로 동작한다.

실제 AWX 런타임에서도 발생하면:

- 해당 Jupyter/배포 이미지에 AWX SDK가 포함되어 있는지 확인한다.
- AWX 기본 flow 예제의 `_shared/bootstrap_local_awx_sdk.sh`가 필요한 환경인지 확인한다.

### 10.3 `uv sync` 실패

증상:

- 패키지 다운로드 실패
- 사내망/폐쇄망에서 외부 PyPI 접근 실패

대응:

- AWX 플랫폼의 내부 PyPI mirror 설정을 확인한다.
- 운영자가 지정한 `UV_INDEX_URL`, `PIP_INDEX_URL`이 있으면 설정한다.
- `awx/pyproject.toml` 기준으로 설치되는지 확인한다.

참고: 저장소 루트의 기존 `requirements.txt`는 일부 LangChain 핀 충돌이 있을 수 있다. AWX 실행은 `awx/pyproject.toml`을 기준으로 한다.

### 10.4 DB 쓰기 실패

증상:

- SQLite 생성 실패
- checkpoint 저장 실패

대응:

```bash
export PATH_TEMP=/tmp
export DATABASE_URL="sqlite:///$PATH_TEMP/banking_demo.db"
export CHECKPOINT_DB_PATH="$PATH_TEMP/banking_checkpoints.db"
```

운영 서비스에서는 SQLite 대신 외부 DB를 AWX external resource/credential로 연결하는 것을 권장한다.

### 10.5 포트 접속 실패

확인:

```bash
echo $FLASK_PORT
```

대응:

```bash
export FLASK_PORT=8001
awx run
```

그리고 플랫폼 proxy에서 같은 포트를 연다.

### 10.6 `Permission denied: run-application.sh`

대응:

```bash
chmod +x run-application.sh
```

---

## 11. 운영 체크리스트

배포 전:

- [ ] `awx/awx-bootstrap.json`의 `service_id`가 실제 값이다.
- [ ] `AWX_CREDENTIAL_SERVICE_ID` 기본값 또는 환경 변수가 실제 값이다.
- [ ] `python scripts/build_awx_flow.py --clean`으로 산출물을 새로 만들었다.
- [ ] AWX workspace의 `flow/`에 산출물만 올라가 있다.
- [ ] `.env`, DB, venv, `.git`이 패키징 대상에 없다.
- [ ] `awx run`으로 `/chat` 접속까지 확인했다.
- [ ] 주요 스모크 시나리오를 통과했다.
- [ ] AWX trace/LLMLog가 적재되는지 확인했다.

배포 후:

- [ ] `/chat` 접속 가능
- [ ] `/agent-logs/` 조회 가능
- [ ] A2A card endpoint 응답
- [ ] credential 기반 LLM 호출 확인
- [ ] collector/LLMLog 오류가 앱 응답 실패로 전파되지 않음

