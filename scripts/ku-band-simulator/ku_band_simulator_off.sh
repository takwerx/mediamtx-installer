#!/bin/bash
# Turn OFF Ku-band simulator. Run on the same box as _on.sh. Requires root.
# Usage: sudo ./ku_band_simulator_off.sh

set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG="${SCRIPT_DIR}/ku_band_simulator.conf"

if [ ! -f "$CONFIG" ]; then
  INTERFACE="${INTERFACE:-eth0}"
else
  # Read the config as data (this script runs as root): never `source` it.
  INTERFACE="$(grep -m1 -E '^INTERFACE=' "$CONFIG" | cut -d= -f2- | tr -d '"\047\r' || true)"
  INTERFACE="${INTERFACE:-eth0}"
fi
if ! [[ "$INTERFACE" =~ ^[A-Za-z0-9_][A-Za-z0-9_.:@-]{0,14}$ ]]; then
  echo "INTERFACE is not a valid interface name."
  exit 1
fi

# Remove netem from ifb0 first, then ingress from the real interface
tc qdisc del dev ifb0 root 2>/dev/null || true
tc qdisc del dev "$INTERFACE" ingress 2>/dev/null || true

echo "Ku-band simulator OFF."
