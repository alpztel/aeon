#!/usr/bin/env bash
# Run ON THE VM as root, after setup-vm.sh. Makes the running AEON backend (Docker Compose) serve the
# SPHEREx files the weekly ingest writes to /data/aeon:
#   1. finds the backend container and the compose project that started it,
#   2. copies the FITS files the backend already has into /data/aeon (never overwrites, never deletes),
#   3. sets AEON_FITS_SOURCE=/data/aeon in the project's .env (backup kept),
#   4. updates the code (git pull --ff-only) and rebuilds/recreates ONLY the backend container,
#   5. waits for /api/v1/health and prints the number of SPHEREx frames served.
# Safe to re-run.
#
#   sudo bash aeon/deploy/azure/link-backend.sh
set -euo pipefail
trap 'echo "link-backend.sh: line $LINENO failed (exit $?)" >&2' ERR
[ "$(id -u)" -eq 0 ] || { echo "run with sudo"; exit 1; }

DATA_DIR=/data/aeon
say() { printf '\n==> %s\n' "$*"; }

say "Backend container"
CID="$(docker ps -q --filter label=com.docker.compose.service=backend | head -1)"
[ -n "$CID" ] || { echo "no running compose service named 'backend' found (docker ps)"; exit 1; }
WORKDIR="$(docker inspect -f '{{ index .Config.Labels "com.docker.compose.project.working_dir" }}' "$CID")"
CONFIGS="$(docker inspect -f '{{ index .Config.Labels "com.docker.compose.project.config_files" }}' "$CID")"
PROJECT="$(docker inspect -f '{{ index .Config.Labels "com.docker.compose.project" }}' "$CID")"
SRC="$(docker inspect -f '{{ range .Mounts }}{{ if eq .Destination "/data/fits" }}{{ .Source }}{{ end }}{{ end }}' "$CID")"
echo "container : $(docker inspect -f '{{.Name}}' "$CID")"
echo "project   : $PROJECT  ($WORKDIR)"
echo "compose   : $CONFIGS"
echo "data now  : ${SRC:-<none>} -> /data/fits"

mkdir -p "$DATA_DIR"
if [ -n "$SRC" ] && [ "$(readlink -f "$SRC")" != "$(readlink -f "$DATA_DIR")" ]; then
  say "Copy existing FITS files into $DATA_DIR (no overwrite)"
  before="$(find "$DATA_DIR" -name '*.fits*' | wc -l)"
  cp -an "$SRC/." "$DATA_DIR/"
  after="$(find "$DATA_DIR" -name '*.fits*' | wc -l)"
  echo "FITS files in $DATA_DIR: $before -> $after"
fi
id aeon >/dev/null 2>&1 && chown -R aeon:aeon "$DATA_DIR"
chmod -R a+rX "$DATA_DIR"

say "Set AEON_FITS_SOURCE=$DATA_DIR in $WORKDIR/.env"
ENVF="$WORKDIR/.env"
touch "$ENVF"
cp -p "$ENVF" "$ENVF.bak-$(date -u +%Y%m%dT%H%M%SZ)"
if grep -q '^AEON_FITS_SOURCE=' "$ENVF"; then
  sed -i "s#^AEON_FITS_SOURCE=.*#AEON_FITS_SOURCE=$DATA_DIR#" "$ENVF"
else
  printf '\nAEON_FITS_SOURCE=%s\n' "$DATA_DIR" >> "$ENVF"
fi

say "Update code"
if git -C "$WORKDIR" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  git -C "$WORKDIR" pull --ff-only || { echo "git pull failed (local changes?) — fix the checkout in $WORKDIR and re-run"; exit 1; }
else
  echo "$WORKDIR is not a git checkout; using the code as it is"
fi

say "Rebuild and recreate only the backend"
ARGS=()
IFS=',' read -ra FILES <<< "$CONFIGS"
for f in "${FILES[@]}"; do ARGS+=(-f "$f"); done
( cd "$WORKDIR" && docker compose -p "$PROJECT" "${ARGS[@]}" up -d --build --no-deps backend )

say "Wait for the backend"
NEW="$(docker ps -q --filter label=com.docker.compose.service=backend --filter "label=com.docker.compose.project=$PROJECT" | head -1)"
for i in $(seq 1 60); do
  if out="$(docker exec "$NEW" python -c "import urllib.request,json;print(json.load(urllib.request.urlopen('http://localhost:8000/api/v1/health',timeout=5))['engines'].get('archive_spherex_frames'))" 2>/dev/null)"; then
    MOUNT="$(docker inspect -f '{{ range .Mounts }}{{ if eq .Destination "/data/fits" }}{{ .Source }}{{ end }}{{ end }}' "$NEW")"
    echo "backend healthy — SPHEREx frames served: $out"
    echo "mount     : $MOUNT -> /data/fits"
    if [ "$(readlink -f "$MOUNT")" != "$(readlink -f "$DATA_DIR")" ]; then
      echo "WARNING: the backend still reads $MOUNT. Its compose file does not use \${AEON_FITS_SOURCE};"
      echo "         update the checkout in $WORKDIR to the latest main and re-run this script."
      exit 1
    fi
    exit 0
  fi
  sleep 5
done
echo "backend did not become healthy in 5 minutes; logs:"
docker logs --tail 40 "$NEW"
exit 1
