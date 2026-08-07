#!/usr/bin/env bash
#
# run.sh — build & start the whole AI HR Assistant project with one command.
#
#   ./run.sh
#
# What it does:
#   1. Checks Docker is installed and the daemon is running.
#   2. Detects Ollama: reuses a native Ollama on :11434 if present (fastest,
#      no downloads); otherwise starts the containerized Ollama
#      (`local-models` profile) and pulls nomic-embed-text.
#   3. Builds + starts the stack (postgres, minio, backend, worker, frontend)
#      — safe to re-run any time (idempotent; images only rebuild on changes).
#   4. Waits until the backend and frontend are healthy.
#   5. Prints the URLs and opens the UI in your browser.
#
# Ports are read from .env (if present): postgres=5434, minio=9200/9201,
# backend=8000, frontend=3000. Stop everything with: docker compose down

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

CYAN='\033[0;36m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
info() { echo -e "${CYAN}[run]${NC} $*"; }
ok()   { echo -e "${GREEN}[ok]${NC} $*"; }
warn() { echo -e "${YELLOW}[warn]${NC} $*"; }
fail() { echo -e "${RED}[error]${NC} $*" >&2; exit 1; }

# Load .env (if any) so the script's defaults match compose (ports, creds).
if [ -f .env ]; then
  set -a; # shellcheck disable=SC1091
  . ./.env
  set +a
fi

# 1. Docker present + daemon running.
command -v docker >/dev/null 2>&1 || fail "docker is not installed (https://docs.docker.com/engine/install/)."
if ! docker info >/dev/null 2>&1 && DOCKER_CONTEXT=default docker info >/dev/null 2>&1; then
  warn "Current Docker context is unreachable — falling back to 'default'."
  export DOCKER_CONTEXT=default
fi
docker info >/dev/null 2>&1 || fail "Docker daemon is not running — start Docker Desktop (or dockerd) and re-run ./run.sh"

# 2. Ollama: native first, containerized fallback.
OLLAMA_PORT="${OLLAMA_PORT:-11434}"
DOCKER_OLAMA=0
if curl -sf -m 2 "http://localhost:${OLLAMA_PORT}/api/tags" >/dev/null 2>&1; then
  ok "Using the native Ollama on :${OLLAMA_PORT} (no model download needed)."
  # A native Ollama that only listens on 127.0.0.1 is unreachable from Docker
  # containers. If socat is available, bridge docker0:PORT -> 127.0.0.1:PORT so
  # the backend/worker can reach it via host.docker.internal.
  if command -v socat >/dev/null 2>&1 && command -v ss >/dev/null 2>&1 && command -v ip >/dev/null 2>&1; then
    DOCKER0_IP="$(ip -4 -o addr show docker0 2>/dev/null | awk '{print $4}' | cut -d/ -f1)"
    if [ -n "$DOCKER0_IP" ] \
      && ss -ltn 2>/dev/null | grep -q "127.0.0.1:${OLLAMA_PORT}" \
      && ! ss -ltn 2>/dev/null | grep -q "${DOCKER0_IP}:${OLLAMA_PORT}"; then
      setsid socat "TCP-LISTEN:${OLLAMA_PORT},bind=${DOCKER0_IP},fork,reuseaddr" \
        "TCP:127.0.0.1:${OLLAMA_PORT}" \
        >/tmp/ollama-docker-bridge.log 2>&1 < /dev/null &
      sleep 1
      ok "Bridged native Ollama to ${DOCKER0_IP}:${OLLAMA_PORT} for Docker containers."
    fi
  fi
else
  warn "No native Ollama on :${OLLAMA_PORT} — starting the containerized Ollama (local-models profile)."
  DOCKER_OLAMA=1
fi

# 3. Build + start the stack.
info "Building and starting the stack (first run downloads images, this can take a while)…"
if [ "$DOCKER_OLAMA" -eq 1 ]; then
  docker compose --profile local-models up -d --build
  info "Pulling the embedding model into the containerized Ollama…"
  docker compose exec -T ollama ollama pull nomic-embed-text \
    || warn "could not pull nomic-embed-text — embeddings will fail until you run it manually"
else
  docker compose up -d --build
fi

BACKEND_URL="http://localhost:${BACKEND_HOST_PORT:-8000}"
FRONTEND_URL="http://localhost:${FRONTEND_HOST_PORT:-3000}"

# 4. Wait for health.
info "Waiting for the backend at ${BACKEND_URL}…"
for _ in $(seq 1 60); do
  curl -sf -m 2 "${BACKEND_URL}/health" >/dev/null 2>&1 && { ok "backend is healthy"; break; }
  sleep 2
done
curl -sf -m 2 "${BACKEND_URL}/health" >/dev/null 2>&1 \
  || fail "backend did not become healthy — check: docker compose logs backend"

info "Waiting for the frontend at ${FRONTEND_URL}…"
for _ in $(seq 1 60); do
  code="$(curl -s -o /dev/null -m 2 -w '%{http_code}' "${FRONTEND_URL}/" || true)"
  [ "$code" = "200" ] || [ "$code" = "307" ] && { ok "frontend is up"; break; }
  sleep 2
done
code="$(curl -s -o /dev/null -m 2 -w '%{http_code}' "${FRONTEND_URL}/" || true)"
[ "$code" = "200" ] || [ "$code" = "307" ] \
  || fail "frontend did not come up — check: docker compose logs frontend"

# 5. Summary.
echo
echo -e "${GREEN}======================================================${NC}"
echo -e "${GREEN}  AI HR Assistant is running 🎉${NC}"
echo -e "${GREEN}======================================================${NC}"
echo "  UI (frontend):      ${FRONTEND_URL}"
echo "  Backend API docs:   ${BACKEND_URL}/docs"
echo "  MinIO console:      http://localhost:${MINIO_CONSOLE_PORT:-9201}   (minioadmin / minioadmin)"
echo "  PostgreSQL:         localhost:${POSTGRES_HOST_PORT:-5434}  (hr / hr, db hr_assistant)"
echo
echo "  Watch ingestion:    docker compose logs -f worker"
echo "  Stop everything:    docker compose down"
echo "  Reset all data:     docker compose down -v"
echo

# 6. Open the browser (best effort).
if command -v xdg-open >/dev/null 2>&1; then
  (xdg-open "${FRONTEND_URL}" >/dev/null 2>&1 &) || true
elif command -v open >/dev/null 2>&1; then
  (open "${FRONTEND_URL}" >/dev/null 2>&1 &) || true
fi
