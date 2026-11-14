#!/usr/bin/env bash
# One-time setup ON THE VM (Ubuntu 22.04/24.04). Installs the ingest job and its weekly timer.
#
#   sudo BLOB_ACCOUNT_URL=https://<account>.blob.core.windows.net bash aeon/deploy/azure/setup-vm.sh
#
# Re-running updates the code and the units. BLOB_ACCOUNT_URL may be left empty (local files only).
set -euo pipefail
[ "$(id -u)" -eq 0 ] || { echo "run with sudo"; exit 1; }

REPO_SRC="$(cd "$(dirname "$0")/../.." && pwd)"
# On re-runs keep the values from the previous install unless new ones are given.
if [ -f /etc/aeon/ingest.env ]; then
  PREV_URL="$(sed -n 's/^AEON_BLOB_ACCOUNT_URL=//p' /etc/aeon/ingest.env)"
  PREV_CONTAINER="$(sed -n 's/^AEON_BLOB_CONTAINER=//p' /etc/aeon/ingest.env)"
fi
BLOB_ACCOUNT_URL="${BLOB_ACCOUNT_URL:-${PREV_URL:-}}"
BLOB_CONTAINER="${BLOB_CONTAINER:-${PREV_CONTAINER:-aeon-data}}"
case "$BLOB_ACCOUNT_URL" in
  ""|https://*.blob.core.windows.net|https://*.blob.core.windows.net/) ;;
  *) echo "BLOB_ACCOUNT_URL must look like https://<account>.blob.core.windows.net"; exit 1 ;;
esac
DATA_DIR=/data/aeon

say() { printf '\n\033[1m==> %s\033[0m\n' "$*"; }

say "Packages"
apt-get update -qq
DEBIAN_FRONTEND=noninteractive apt-get install -y -qq python3-venv python3-dev build-essential git rsync >/dev/null

say "Service user 'aeon'"
id aeon >/dev/null 2>&1 || useradd --system --create-home --shell /usr/sbin/nologin aeon

say "Data disk -> $DATA_DIR"
if ! mountpoint -q /data; then
  # The empty data disk created by provision.sh (no partitions, not mounted).
  DISK="$(lsblk -dpno NAME,TYPE,MOUNTPOINT | awk '$2=="disk" && $3=="" {print $1}' | while read -r d; do
            [ -z "$(lsblk -no PARTTYPE "$d" | tr -d '[:space:]')" ] && ! blkid "$d" >/dev/null 2>&1 && echo "$d"; done | head -1)"
  if [ -n "$DISK" ]; then
    echo "formatting empty disk $DISK"
    mkfs.ext4 -q -L aeondata "$DISK"
    mkdir -p /data
    echo "LABEL=aeondata /data ext4 defaults,nofail 0 2" >> /etc/fstab
    mount /data
  else
    echo "no empty data disk found: using the OS disk for /data"
    mkdir -p /data
  fi
fi
mkdir -p "$DATA_DIR" "$DATA_DIR/.home"
chown -R aeon:aeon "$DATA_DIR"

say "Code -> /opt/aeon/repo"
mkdir -p /opt/aeon
rsync -a --delete --exclude .git --exclude node_modules "$REPO_SRC/" /opt/aeon/repo/
chown -R root:root /opt/aeon/repo

say "Python environment -> /opt/aeon/venv"
[ -x /opt/aeon/venv/bin/python ] || python3 -m venv /opt/aeon/venv
/opt/aeon/venv/bin/pip install -q --upgrade pip
/opt/aeon/venv/bin/pip install -q -r /opt/aeon/repo/backend/requirements.txt -r /opt/aeon/repo/deploy/azure/requirements.txt

say "Configuration -> /etc/aeon/ingest.env"
mkdir -p /etc/aeon
cat > /etc/aeon/ingest.env <<EOF
AEON_DATA_DIR=$DATA_DIR
AEON_BLOB_ACCOUNT_URL=$BLOB_ACCOUNT_URL
AEON_BLOB_CONTAINER=$BLOB_CONTAINER
MALLOC_ARENA_MAX=2
EOF

say "systemd units"
install -m 0644 /opt/aeon/repo/deploy/azure/aeon-ingest.service /etc/systemd/system/aeon-ingest.service
install -m 0644 /opt/aeon/repo/deploy/azure/aeon-ingest.timer /etc/systemd/system/aeon-ingest.timer
systemctl daemon-reload
systemctl enable --now aeon-ingest.timer

cat <<EOF

Installed. Useful commands:
  sudo systemctl start aeon-ingest.service      # run now (first run: a few minutes)
  journalctl -u aeon-ingest.service -f          # watch the log
  systemctl list-timers aeon-ingest.timer       # next scheduled run
  ls $DATA_DIR/runs                             # one JSON report per run
EOF
