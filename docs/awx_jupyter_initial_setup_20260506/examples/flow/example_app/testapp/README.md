# testapp

`make init` / `make run` / smoke 테스트를 위한 가장 작은 내부 FastAPI 예제입니다.

## 이 예제를 먼저 볼 때

- 사용자 기능 예제보다 launcher/Makefile 동작만 빠르게 확인하고 싶을 때
- AWX SDK 연동 없이 기본 FastAPI boot 경로만 검증하고 싶을 때
- 회귀 테스트용 최소 앱이 필요할 때

## Quick Start

```bash
cd /home/user/idea-project/container-script/example_awx/flow
make init app=testapp
make sync
make run
```

## 실제 구동 환경과 로컬 차이

- 실제 구동 기준은 builder/inference runtime이지만, 이 앱은 운영 기능 예제보다 launcher smoke 검증에 더 가깝습니다.
- 지금 저장소에서 확인하는 로컬 실행은 `make init`, `make run`, 기본 `/health` 응답 확인 범위입니다.
- 이 예제는 별도 실환경 값이 거의 없지만, path/layout과 injected metadata는 실제 runtime과 다를 수 있습니다.
- 실제 환경 변수가 필요하면 저장소 값에 기대하지 말고 사용자/운영자에게 요청하세요.
