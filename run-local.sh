#!/usr/bin/env bash
# VP/run-local.sh
# 백엔드(FastAPI) + MCP 서버 + 프론트엔드(Vite)를 한 번에 띄운다.
set -euo pipefail
cd "$(dirname "$0")"

pids=()
cleanup() {
  echo ""
  echo "[run-local] stopping..."
  for pid in "${pids[@]:-}"; do
    kill "$pid" 2>/dev/null || true
  done
}
trap cleanup EXIT INT TERM

echo "[run-local] starting backend (uvicorn app.main:app --port 8000)"
python -m uvicorn app.main:app --reload --port 8000 &
pids+=($!)

echo "[run-local] starting MCP server (uvicorn vp_mcp.mcp_server.server:app --port 5177)"
python -m uvicorn vp_mcp.mcp_server.server:app --reload --port 5177 &
pids+=($!)

echo "[run-local] starting frontend (FE: npm run dev)"
(cd FE && npm run dev -- --host 0.0.0.0) &
pids+=($!)

wait
