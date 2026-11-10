#!/bin/bash
# Turn ON Ku-band-like impairment for incoming traffic from the sending MediaMTX.
# Run on the RECEIVER box (the one that pulls the stream as external source).
# Requires root. Usage: sudo ./ku_band_simulator_on.sh

set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG="${SCRIPT_DIR}/ku_band_simulator.conf"

if [ ! -f "$CONFIG" ]; then
  echo "Missing $CONFIG. Copy ku_band_simulator.conf.example and set SOURCE_IP and INTERFACE."
  exit 1
fi
# This script runs as root. Read the config as data (KEY=value lines), never `source` it:
# sourcing would run anything written in the file. Every value is checked before use.
conf_get() {
  grep -m1 -E "^$1=" "$CONFIG" | cut -d= -f2- | tr -d '"\047\r' || true
}
# conf_or KEY DEFAULT: the config value, else DEFAULT
conf_or() {
  local v
  v="$(conf_get "$1")"
  printf '%s' "${v:-$2}"
}
SOURCE_IP="$(conf_get SOURCE_IP)"
INTERFACE="$(conf_get INTERFACE)"

if [ -z "$SOURCE_IP" ] || [ -z "$INTERFACE" ]; then
  echo "Set SOURCE_IP (sending MediaMTX IP) and INTERFACE (e.g. eth0) in $CONFIG"
  exit 1
fi
if ! [[ "$SOURCE_IP" =~ ^[0-9]{1,3}(\.[0-9]{1,3}){3}$ ]]; then
  echo "SOURCE_IP in $CONFIG is not an IPv4 address."
  exit 1
fi
if ! [[ "$INTERFACE" =~ ^[A-Za-z0-9_][A-Za-z0-9_.:@-]{0,14}$ ]]; then
  echo "INTERFACE in $CONFIG is not a valid interface name."
  exit 1
fi

# Ku-band-like: high RTT, jitter, some loss (tweak as needed). Config value, else environment, else default.
DELAY_MS="$(conf_or DELAY_MS "${DELAY_MS:-600}")"
JITTER_MS="$(conf_or JITTER_MS "${JITTER_MS:-100}")"
LOSS_PCT="$(conf_or LOSS_PCT "${LOSS_PCT:-1}")"
for v in "$DELAY_MS" "$JITTER_MS" "$LOSS_PCT"; do
  if ! [[ "$v" =~ ^[0-9]+(\.[0-9]+)?$ ]]; then
    echo "DELAY_MS, JITTER_MS and LOSS_PCT in $CONFIG must be numbers."
    exit 1
  fi
done

# Already on?
if tc qdisc show dev "$INTERFACE" | grep -q ingress; then
  echo "Simulator already ON (ingress on $INTERFACE). Run ku_band_simulator_off.sh first."
  exit 0
fi

modprobe ifb 2>/dev/null || true
ip link set dev ifb0 up 2>/dev/null || true

# Redirect ingress from SOURCE_IP to ifb0
tc qdisc add dev "$INTERFACE" ingress
tc filter add dev "$INTERFACE" parent ffff: protocol ip u32 match ip src "$SOURCE_IP" action mirred egress redirect dev ifb0

# Apply impairment on ifb (affects the redirected incoming traffic)
tc qdisc add dev ifb0 root netem delay "${DELAY_MS}ms" "${JITTER_MS}ms" loss "${LOSS_PCT}%"

echo "Ku-band simulator ON: traffic from $SOURCE_IP -> $INTERFACE delayed ${DELAY_MS}ms ±${JITTER_MS}ms, ${LOSS_PCT}% loss."
