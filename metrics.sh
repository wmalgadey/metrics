#!/usr/bin/env bash
# Wrapper around podman for the azdo-metrics CLI and dashboard stack.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

IMAGE="localhost/azdo-metrics:latest"
ENGINE="${CONTAINER_ENGINE:-podman}"

usage() {
  cat <<'EOF'
Usage: ./metrics.sh <command> [args...]

  init [args...]      Run `metrics init` (discover sprints, write config.yaml)
  sync [args...]       Run `metrics sync` (fetch + store + export)
  export [args...]     Run `metrics export` (push local metrics to VictoriaMetrics)
  sprints [args...]    Run `metrics sprints ...`
  status [args...]     Run `metrics status`
  shell                Open a shell inside the CLI image
  build                (Re)build the CLI image
  dashboard [up|down]  Start/stop VictoriaMetrics + Perses (default: up)

Setup: copy .env.example to .env and set AZDO_PAT before running init/sync.
Data persists in ./data (created on first run).
EOF
}

compose() {
  if command -v podman-compose >/dev/null 2>&1; then
    podman-compose -f podman-compose.yml "$@"
  else
    "$ENGINE" compose -f podman-compose.yml "$@"
  fi
}

build_image() {
  "$ENGINE" build -t "$IMAGE" -f Containerfile .
}

ensure_image() {
  "$ENGINE" image exists "$IMAGE" 2>/dev/null || build_image
}

ensure_env() {
  [ -f .env ] || cp .env.example .env
  mkdir -p data
}

# Common run flags: --userns=keep-id:uid=1000,gid=1000 makes the container's
# non-root `metrics` user (baked in as UID 1000, see Containerfile) own files
# it writes under ./data regardless of the invoking host user's own UID.
# --network host lets the container reach VictoriaMetrics via localhost:8428
# (published by `dashboard up`) as well as the internet (Azure DevOps).
run_container() {
  local -a mounts=(-v "$(pwd)/data:/app/data:Z")
  if [ -f config.yaml ]; then
    mounts+=(-v "$(pwd)/config.yaml:/app/config.yaml:Z")
  fi
  "$ENGINE" run --rm -it \
    --userns=keep-id:uid=1000,gid=1000 \
    --network host \
    --env-file .env \
    "${mounts[@]}" \
    "$@"
}

run_cli() {
  ensure_image
  ensure_env
  if [ "$1" = "init" ] && [ ! -f config.yaml ]; then
    touch config.yaml  # give init a persistent file to write into
  fi
  run_container "$IMAGE" "$@"
}

dashboard_cmd() {
  case "${1:-up}" in
    up)
      mkdir -p data/vm-data
      compose up -d victoriametrics perses
      echo "VictoriaMetrics: http://localhost:8428"
      echo "Perses:          http://localhost:8080"
      ;;
    down) compose down ;;
    *) echo "Usage: ./metrics.sh dashboard [up|down]" >&2; exit 1 ;;
  esac
}

cmd="${1:-}"
case "$cmd" in
  init|sync|export|status|sprints) run_cli "$@" ;;
  shell)
    ensure_image
    ensure_env
    run_container --entrypoint bash "$IMAGE"
    ;;
  build) build_image ;;
  dashboard) shift; dashboard_cmd "$@" ;;
  -h|--help|help|"") usage ;;
  *) echo "Unknown command: $cmd" >&2; usage; exit 1 ;;
esac
