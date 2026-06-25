# AWX Flow Wrapper

This directory is not a second source tree. The canonical application remains at
the repository root (`app.py`, `config.py`, `src/`, `templates/`, `static/`).

Use `scripts/build_awx_flow.py` to assemble an AWX packaging directory:

```bash
python scripts/build_awx_flow.py --clean
```

The generated output is `dist/awx-flow/` and contains:

- `run-application.sh`
- `awx-bootstrap.json`
- `pyproject.toml`
- canonical app source copied from the repository root

After generation, run or package from the generated flow directory:

```bash
cd dist/awx-flow
bash run-application.sh
# or in AWX runtime:
awx run
awx package --message "ai-banking-transfer-agent awx migration"
```

Credential defaults in `awx-bootstrap.json` are placeholders based on the AWX
examples. Replace `service_id` and related metadata with the values assigned to
the target AgenticWorks project before production packaging.

