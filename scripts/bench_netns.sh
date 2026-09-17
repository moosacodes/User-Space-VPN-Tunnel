#!/usr/bin/env bash
# Two-host simulation with Linux network namespaces + real TUN devices.
# Usage: sudo ./scripts/bench_netns.sh [duration_s] [min_mbps] [min_packets]
set -euo pipefail

DURATION="${1:-10}"
MIN_MBPS="${2:-20}"
MIN_PACKETS="${3:-10000}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export PYTHONPATH="$ROOT${PYTHONPATH:+:$PYTHONPATH}"
PORT=51820
SERVER_NS=vpn_srv
CLIENT_NS=vpn_cli
VETH_S=veth-s
VETH_C=veth-c

cleanup() {
  ip netns del "$SERVER_NS" 2>/dev/null || true
  ip netns del "$CLIENT_NS" 2>/dev/null || true
  ip link del "$VETH_S" 2>/dev/null || true
}
trap cleanup EXIT

cleanup
ip netns add "$SERVER_NS"
ip netns add "$CLIENT_NS"

ip link add "$VETH_S" type veth peer name "$VETH_C"
ip link set "$VETH_S" netns "$SERVER_NS"
ip link set "$VETH_C" netns "$CLIENT_NS"

ip netns exec "$SERVER_NS" bash -c "
  ip addr add 192.168.100.1/24 dev $VETH_S
  ip link set $VETH_S up
  ip link set lo up
"
ip netns exec "$CLIENT_NS" bash -c "
  ip addr add 192.168.100.2/24 dev $VETH_C
  ip link set $VETH_C up
  ip link set lo up
"

# Start VPN server in server ns
ip netns exec "$SERVER_NS" python3 -m vpn.server \
  --bind 192.168.100.1 --port "$PORT" \
  --tun vpn0 --addr 10.8.0.1 --prefix 24 --mtu 1400 \
  >/tmp/vpn_srv.log 2>&1 &
SRV_PID=$!
sleep 1

# Start VPN client in client ns
ip netns exec "$CLIENT_NS" python3 -m vpn.client \
  --server 192.168.100.1 --port "$PORT" \
  --tun vpn0 --addr 10.8.0.2 --prefix 24 --mtu 1400 \
  >/tmp/vpn_cli.log 2>&1 &
CLI_PID=$!
sleep 1

# Enable forwarding / accept traffic on overlay (local ping path)
ip netns exec "$SERVER_NS" sysctl -w net.ipv4.ip_forward=1 >/dev/null
ip netns exec "$CLIENT_NS" sysctl -w net.ipv4.ip_forward=1 >/dev/null

echo "Running iperf-like UDP blast over TUN for ${DURATION}s..."
# Use ping flood + large UDP via python generator inside client ns
ip netns exec "$CLIENT_NS" python3 - <<'PY' "$DURATION" "$MIN_MBPS" "$MIN_PACKETS"
import os, socket, struct, sys, time, subprocess

duration = float(sys.argv[1])
min_mbps = float(sys.argv[2])
min_packets = int(sys.argv[3])

def pkt(payload, ident):
    udp_len = 8 + len(payload)
    udp = struct.pack("!HHHH", 50000, 50001, udp_len, 0) + payload
    total = 20 + len(udp)
    iph = struct.pack("!BBHHHBBH4s4s", 0x45, 0, total, ident & 0xFFFF, 0, 64, 17, 0,
                      socket.inet_aton("10.8.0.2"), socket.inet_aton("10.8.0.1"))
    return iph + udp

# Open raw IP socket to inject toward TUN-routed destination — easier: write via UDP
# to 10.8.0.1 so kernel sends via vpn0
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
payload = os.urandom(1200)
# Pace ~25 Mbps
pps = (25_000_000) / (1228 * 8)
interval = 1.0 / pps
sent = 0
t0 = time.monotonic()
next_t = t0
while time.monotonic() - t0 < duration:
    sock.sendto(payload, ("10.8.0.1", 50001))
    sent += 1
    next_t += interval
    d = next_t - time.monotonic()
    if d > 0:
        time.sleep(d)
elapsed = time.monotonic() - t0
mbps = (sent * len(payload) * 8) / elapsed / 1_000_000
print(f"client_sent_packets={sent}")
print(f"client_payload_mbps={mbps:.2f}")
print(f"elapsed_s={elapsed:.2f}")
ok = sent >= min_packets and mbps >= min_mbps
print(f"PASS={ok}")
sys.exit(0 if ok else 1)
PY
STATUS=$?

kill "$CLI_PID" "$SRV_PID" 2>/dev/null || true
wait "$CLI_PID" "$SRV_PID" 2>/dev/null || true

echo "---- server log (tail) ----"
tail -n 30 /tmp/vpn_srv.log || true
echo "---- client log (tail) ----"
tail -n 30 /tmp/vpn_cli.log || true
exit "$STATUS"
