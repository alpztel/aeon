#!/usr/bin/env bash
# Tests find_empty_disk() from setup-vm.sh with stubbed lsblk / blkid (no real disks touched).
# Run: bash deploy/azure/test_setup_disk.sh
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
# Load only the function definition.
eval "$(sed -n '/^find_empty_disk() {/,/^}/p' "$HERE/setup-vm.sh")"

fail=0
check() {  # name expected
  local got
  got="$(find_empty_disk)"
  if [ "$got" = "$2" ]; then echo "ok   - $1"; else echo "FAIL - $1: expected '$2', got '$got'"; fail=1; fi
}

# Scenario stubs: DISKS = "name:children:mount:signature" entries
lsblk() {
  local args="$*" d
  if [[ "$args" == "-dpno NAME,TYPE" ]]; then
    for d in $DISKS; do echo "${d%%:*} disk"; done
    return 0
  fi
  local dev="${*: -1}"
  for d in $DISKS; do
    IFS=: read -r name children mount sig <<< "$d"
    [ "$name" = "$dev" ] || continue
    if [[ "$args" == -no\ NAME* ]]; then
      echo "$name"; for _ in $(seq 1 "$children"); do echo "${name}p"; done
    elif [[ "$args" == -no\ MOUNTPOINT* ]]; then
      echo ""; [ "$mount" = "-" ] || echo "$mount"
    fi
  done
}
blkid() {
  local dev="${*: -1}" d
  for d in $DISKS; do
    IFS=: read -r name children mount sig <<< "$d"
    [ "$name" = "$dev" ] && [ "$sig" = "yes" ] && return 0
  done
  return 2
}

DISKS="/dev/sda:1:/:yes"
check "OS disk only (aeon-api case): nothing, and no failure under set -e" ""

DISKS="/dev/sda:2:/:yes /dev/sdc:0:-:no"
check "OS disk + empty data disk: picks the data disk" "/dev/sdc"

DISKS="/dev/sda:1:/:yes /dev/sdb:1:/mnt:yes"
check "Azure temp disk mounted on /mnt is never picked" ""

DISKS="/dev/sda:1:/:yes /dev/sdc:0:-:yes"
check "disk with a filesystem but no partitions is never formatted" ""

DISKS="/dev/sda:1:/:yes /dev/sdc:1:-:no"
check "disk with a partition is never formatted" ""

DISKS=""
check "no disks at all" ""

exit $fail
