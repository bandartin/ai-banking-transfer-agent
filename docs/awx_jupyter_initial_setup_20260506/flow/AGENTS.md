# Example AWX Flow Rules

- For any `run_app.sh`, `run_client.sh`, or `run_server.sh` that launches `opentelemetry-instrument`, source [example_app/_shared/bootstrap_local_awx_sdk.sh](/home/user/idea-project/container-script/example_awx/flow/example_app/_shared/bootstrap_local_awx_sdk.sh) and call `prepend_awx_sdk_pythonpath "$SCRIPT_DIR"` before starting Python.
- Do not reimplement shell-side mapping from `OTEL_GRPC_*_FROM_INTERNAL/PORTAL` into standard `OTEL_EXPORTER_OTLP_*` inside examples. The SDK runtime bridge in `awx_observability` owns that behavior.
- In example `.env.example` and `README.md`, describe `OTEL_EXPORTER_OTLP_*` only as optional overrides. Do not expose platform-injected AWX OTEL variable names to end users.
- Keep example OTEL endpoint defaults empty unless a specific example truly requires a custom collector override.
