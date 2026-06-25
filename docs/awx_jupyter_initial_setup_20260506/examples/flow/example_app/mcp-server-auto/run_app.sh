#!/bin/bash
HOST=${1:-0.0.0.0}
PORT=${2:-8000}

cd server
bash run_server.sh "$HOST" "$PORT"
