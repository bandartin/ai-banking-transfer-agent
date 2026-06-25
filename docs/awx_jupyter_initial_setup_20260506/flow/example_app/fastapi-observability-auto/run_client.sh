#!/bin/bash
HOST=${1:-0.0.0.0}
PORT=${2:-8000}

cd client
bash run_client.sh "$HOST" "$PORT"
