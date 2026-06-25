#!/bin/bash
# Auto-generated: ensures ${PATH_WORK}/flow/run-application.sh exists and is non-empty
cd /workspace || exit 1

# 가상환경 활성화
source /opt/venv/bin/activate

# prompt-optimizer-mcp 서버 실행
python -m prompt_optimizer.server
