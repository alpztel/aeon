#!/usr/bin/env bash
# Run ON THE VM as root. Brings the live AEON API up to date with GitHub main in one step:
#   1. finds the running compose project (from the backend container's labels),
#   2. git pull --ff-only in that checkout (stops if the checkout has local changes),
#   3. rebuilds and restarts every service of the project (backend, ai-engine, multi-mission-api,
#      nginx, certbot) — the "full" profile is kept if ai-engine / multi-mission-api were running,
#   4. waits until backend, ai-engine and multi-mission-api answer their health checks,
#   5. refreshes the weekly ingest job (setup-vm.sh) when /root/aeon exists,
#   6. removes dangling images.
# Nothing to do when main has not moved (set FORCE=1 to rebuild anyway). Safe to re-run.
#
#   sudo bash /root/aeon/deploy/azure/update-api.sh
set -euo pipefail
trap 'echo "update-api.sh: line $LINENO failed (exit $?)" >&2' ERR

INGEST_REPO="${INGEST_REPO:-/root/aeon}"
FORCE="${FORCE:-0}"
HEALTH_TRIES="${HEALTH_TRIES:-60}"      # x 5 s
HEALTH_SLEEP="${HEALTH_SLEEP:-5}"

say() { printf '\n==> %s\n' "$*"; }

label() {  # label <container> <key>
  docker inspect -f "{{ index .Config.Labels \"$2\" }}" "$1"
}

# Sets CID WORKDIR CONFIGS PROJECT from the running backend container.
discover_project() {
  CID="$(docker ps -q --filter label=com.docker.compose.service=backend | head -1)"
  [ -n "$CID" ] || { echo "no running compose service named 'backend' (docker ps)"; return 1; }
  WORKDIR="$(label "$CID" com.docker.compose.project.working_dir)"
  CONFIGS="$(label "$CID" com.docker.compose.project.config_files)"
  PROJECT="$(label "$CID" com.docker.compose.project)"
  [ -n "$WORKDIR" ] && [ -n "$CONFIGS" ] && [ -n "$PROJECT" ] || { echo "backend container has no compose labels"; return 1; }
}

# Prints the compose CLI arguments (-p, -f ..., --profile full when the full stack was running).
compose_args() {
  local f out=(-p "$PROJECT")
  IFS=',' read -ra _files <<< "$CONFIGS"
  for f in "${_files[@]}"; do out+=(-f "$f"); done
  # Command substitution instead of `| grep -q`: an early-exiting grep can SIGPIPE docker and,
  # under pipefail, turn a match into a failure.
  local svc
  for svc in ai-engine multi-mission-api; do
    if [ -n "$(docker ps -a -q --filter "label=com.docker.compose.project=$PROJECT" --filter "label=com.docker.compose.service=$svc")" ]; then
      out+=(--profile full)
      break
    fi
  done
  printf '%s\n' "${out[@]}"
}

# health <service> <port> <path>: 0 when the service answers, 2 when it is not part of the project.
health() {
  local c
  c="$(docker ps -q --filter "label=com.docker.compose.project=$PROJECT" --filter "label=com.docker.compose.service=$1" | head -1)"
  [ -n "$c" ] || return 2
  docker exec "$c" python -c "import urllib.request; urllib.request.urlopen('http://localhost:$2$3', timeout=5)" >/dev/null 2>&1
}

wait_healthy() {
  local svc port path rc i
  for spec in "backend 8000 /api/v1/health" "ai-engine 8100 /healthz" "multi-mission-api 8200 /healthz"; do
    read -r svc port path <<< "$spec"
    for i in $(seq 1 "$HEALTH_TRIES"); do
      rc=0; health "$svc" "$port" "$path" || rc=$?
      [ "$rc" -eq 0 ] && { echo "ok   $svc"; break; }
      [ "$rc" -eq 2 ] && { echo "--   $svc (not part of this deployment)"; break; }
      [ "$i" -eq "$HEALTH_TRIES" ] && { echo "FAIL $svc did not become healthy"; return 1; }
      sleep "$HEALTH_SLEEP"
    done
  done
}

main() {
  [ "$(id -u)" -eq 0 ] || { echo "run with sudo"; exit 1; }

  say "Compose project"
  discover_project
  echo "project : $PROJECT ($WORKDIR)"
  mapfile -t ARGS < <(compose_args)
  echo "compose : ${ARGS[*]}"

  say "Code"
  git -C "$WORKDIR" rev-parse --is-inside-work-tree >/dev/null 2>&1 || { echo "$WORKDIR is not a git checkout"; exit 1; }
  OLD="$(git -C "$WORKDIR" rev-parse --short HEAD)"
  git -C "$WORKDIR" pull --ff-only --quiet || { echo "git pull failed (local changes in $WORKDIR?) — nothing was restarted"; exit 1; }
  NEW="$(git -C "$WORKDIR" rev-parse --short HEAD)"
  echo "main    : $OLD -> $NEW"

  if [ "$OLD" = "$NEW" ] && [ "$FORCE" != "1" ]; then
    echo "already up to date (FORCE=1 rebuilds anyway)"
  else
    say "Rebuild and restart all services"
    ( cd "$WORKDIR" && docker compose "${ARGS[@]}" up -d --build --remove-orphans )
  fi

  say "Health"
  wait_healthy

  if [ -d "$INGEST_REPO/.git" ]; then
    say "Weekly ingest job"
    git -C "$INGEST_REPO" pull --ff-only --quiet && bash "$INGEST_REPO/deploy/azure/setup-vm.sh" >/dev/null && echo "ingest job updated"
  fi

  say "Cleanup"
  docker image prune -f >/dev/null && echo "dangling images removed"
  echo
  echo "UPDATED: $NEW"
}

# Allow tests to source the functions without running main.
if [ "${BASH_SOURCE[0]}" = "$0" ]; then
  main "$@"
fi
