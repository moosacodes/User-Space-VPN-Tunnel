#!/usr/bin/env bash
# Capture packet flows for debugging routing/NAT/firewall with tcpdump.
# Produces PCAPs suitable for Wireshark.
set -euo pipefail

OUTDIR="${OUTDIR:-./captures}"
mkdir -p "$OUTDIR"
STAMP=$(date +%Y%m%d_%H%M%S)
DURATION="${DURATION:-30}"
UDP_PORT="${UDP_PORT:-51820}"
TUN_IF="${TUN_IF:-vpn0}"
WAN_IF="${WAN_IF:-any}"

echo "Capturing ${DURATION}s -> $OUTDIR (Wireshark-compatible PCAP)"

sudo timeout "$DURATION" tcpdump -i "$WAN_IF" -w "$OUTDIR/wan_${STAMP}.pcap" \
  "udp port $UDP_PORT" &
WAN_PID=$!

if ip link show "$TUN_IF" >/dev/null 2>&1; then
  sudo timeout "$DURATION" tcpdump -i "$TUN_IF" -w "$OUTDIR/tun_${STAMP}.pcap" \
    "ip" &
  TUN_PID=$!
else
  TUN_PID=""
  echo "TUN $TUN_IF not up yet; WAN-only capture"
fi

wait "$WAN_PID" || true
[[ -n "$TUN_PID" ]] && wait "$TUN_PID" || true

echo "Written:"
ls -la "$OUTDIR"/*_"${STAMP}".pcap
cat <<EOF

Wireshark display filters:
  udp.port == $UDP_PORT
  ip.addr == 10.8.0.0/24
  icmp
  tcp.flags.syn==1 && tcp.flags.ack==0

Compare WAN (outer UDP) vs TUN (inner IP) to locate drops:
  - Outer present, inner missing  => decrypt/forward/TUN write issue
  - Inner present, no reply       => routing / NAT / FORWARD chain
  - SYN out, no SYN-ACK           => remote firewall / NAT hairpin
EOF
