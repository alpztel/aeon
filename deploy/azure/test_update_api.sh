#!/usr/bin/env bash
# Tests update-api.sh helpers with a stubbed `docker` (no containers touched).
# Run: bash deploy/azure/test_update_api.sh
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=/dev/null
source "$HERE/update-api.sh"
set +e
trap - ERR

fail=0
ok() { if [ "$2" = "$3" ]; then echo "ok   - $1"; else echo "FAIL - $1: expected [$3] got [$2]"; fail=1; fi; }

# ---- docker stub: SERVICES="name:id ..." ; HEALTHY="id ..." ; LABELS for the backend
docker() {
  case "$1" in
    ps)
      local svc="" proj=""
      for a in "$@"; do
        case "$a" in
          label=com.docker.compose.service=*) svc="${a#label=com.docker.compose.service=}" ;;
          label=com.docker.compose.project=*) proj="${a#label=com.docker.compose.project=}" ;;
        esac
      done
      [ -n "$proj" ] && [ "$proj" != "deploy" ] && return 0
      for s in $SERVICES; do [ "${s%%:*}" = "$svc" ] && echo "${s##*:}"; done
      ;;
    inspect)
      case "$3" in
        *working_dir*) echo "/opt/aeon-api/deploy" ;;
        *config_files*) echo "/opt/aeon-api/deploy/docker-compose.yml,/opt/aeon-api/deploy/docker-compose.prod.yml" ;;
        *project\"*) echo "deploy" ;;
      esac
      ;;
    exec)
      for h in $HEALTHY; do [ "$h" = "$2" ] && return 0; done
      return 1
      ;;
  esac
}

SERVICES="backend:b1 ai-engine:a1 multi-mission-api:m1 nginx:n1"
discover_project
ok "project discovered from backend labels" "$PROJECT|$WORKDIR" "deploy|/opt/aeon-api/deploy"
ok "compose args keep both files and the full profile" "$(compose_args | tr '\n' ' ')" \
   "-p deploy -f /opt/aeon-api/deploy/docker-compose.yml -f /opt/aeon-api/deploy/docker-compose.prod.yml --profile full "

SERVICES="backend:b1 nginx:n1"
ok "backend-only deployment gets no profile" "$(compose_args | tr '\n' ' ')" \
   "-p deploy -f /opt/aeon-api/deploy/docker-compose.yml -f /opt/aeon-api/deploy/docker-compose.prod.yml "

SERVICES=""
discover_project >/dev/null 2>&1
ok "no backend container is an error" "$?" "1"

SERVICES="backend:b1 ai-engine:a1 multi-mission-api:m1"
PROJECT=deploy
HEALTHY="b1 a1 m1"; HEALTH_TRIES=2; HEALTH_SLEEP=0
wait_healthy >/dev/null
ok "all healthy" "$?" "0"

HEALTHY="b1 m1"
out="$(wait_healthy)"; rc=$?
ok "unhealthy ai-engine fails the update" "$rc" "1"
ok "failure names the service" "$(echo "$out" | grep -c 'FAIL ai-engine')" "1"

SERVICES="backend:b1"; HEALTHY="b1"
out="$(wait_healthy)"; rc=$?
ok "services that are not deployed are skipped, not failed" "$rc|$(echo "$out" | grep -c 'not part')" "0|2"

exit $fail
