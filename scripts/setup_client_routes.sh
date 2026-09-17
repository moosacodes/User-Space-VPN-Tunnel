#!/usr/bin/env bash
# Client-side routes / DNS helpers after vpn.client brings up TUN.
set -euo pipefail

TUN_IF="${TUN_IF:-vpn0}"
SERVER_OVERLAY="${SERVER_OVERLAY:-10.8.0.1}"
# Optional: route all traffic through tunnel (full-tunnel). Default is split.
FULL_TUNNEL="${FULL_TUNNEL:-0}"
SERVER_PUBLIC="${SERVER_PUBLIC:-}"

ip route replace "${SERVER_OVERLAY}/32" dev "$TUN_IF"

if [[ "$FULL_TUNNEL" == "1" ]]; then
  if [[ -z "$SERVER_PUBLIC" ]]; then
    echo "FULL_TUNNEL=1 requires SERVER_PUBLIC=<server wan ip>" >&2
    exit 1
  fi
  # Keep path to VPN server via original default GW
  GW=$(ip route show default | awk '{print $3; exit}')
  DEV=$(ip route show default | awk '{print $5; exit}')
  ip route replace "$SERVER_PUBLIC"/32 via "$GW" dev "$DEV"
  ip route replace 0.0.0.0/1 dev "$TUN_IF"
  ip route replace 128.0.0.0/1 dev "$TUN_IF"
  echo "Full-tunnel routes installed via $TUN_IF"
else
  echo "Split-tunnel: only overlay route to $SERVER_OVERLAY via $TUN_IF"
fi
