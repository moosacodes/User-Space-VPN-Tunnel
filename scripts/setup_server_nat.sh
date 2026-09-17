#!/usr/bin/env bash
# Configure host as VPN server: TUN already created by vpn.server; this adds
# IP forwarding, NAT, and firewall rules so clients can reach external nets.
set -euo pipefail

TUN_IF="${TUN_IF:-vpn0}"
WAN_IF="${WAN_IF:-$(ip route show default | awk '{print $5; exit}')}"
OVERLAY="${OVERLAY:-10.8.0.0/24}"
UDP_PORT="${UDP_PORT:-51820}"

if [[ -z "$WAN_IF" ]]; then
  echo "Could not detect WAN interface; set WAN_IF=eth0" >&2
  exit 1
fi

echo "WAN_IF=$WAN_IF TUN_IF=$TUN_IF OVERLAY=$OVERLAY PORT=$UDP_PORT"

sysctl -w net.ipv4.ip_forward=1

# Firewall: allow UDP tunnel + overlay forwarding
if command -v ufw >/dev/null 2>&1 && ufw status | grep -q "Status: active"; then
  ufw allow "${UDP_PORT}/udp" comment "userspace-vpn" || true
  ufw route allow in on "$TUN_IF" out on "$WAN_IF" || true
fi

# nftables / iptables NAT masquerade for overlay clients
if command -v nft >/dev/null 2>&1; then
  nft list table ip vpn 2>/dev/null && nft delete table ip vpn || true
  nft -f - <<EOF
table ip vpn {
  chain postrouting {
    type nat hook postrouting priority srcnat; policy accept;
    oifname "$WAN_IF" ip saddr $OVERLAY masquerade
  }
  chain forward {
    type filter hook forward priority filter; policy accept;
    iifname "$TUN_IF" oifname "$WAN_IF" accept
    iifname "$WAN_IF" oifname "$TUN_IF" ct state related,established accept
  }
  chain input {
    type filter hook input priority filter; policy accept;
    udp dport $UDP_PORT accept
  }
}
EOF
else
  iptables -t nat -C POSTROUTING -s "$OVERLAY" -o "$WAN_IF" -j MASQUERADE 2>/dev/null \
    || iptables -t nat -A POSTROUTING -s "$OVERLAY" -o "$WAN_IF" -j MASQUERADE
  iptables -C FORWARD -i "$TUN_IF" -o "$WAN_IF" -j ACCEPT 2>/dev/null \
    || iptables -A FORWARD -i "$TUN_IF" -o "$WAN_IF" -j ACCEPT
  iptables -C FORWARD -i "$WAN_IF" -o "$TUN_IF" -m state --state RELATED,ESTABLISHED -j ACCEPT 2>/dev/null \
    || iptables -A FORWARD -i "$WAN_IF" -o "$TUN_IF" -m state --state RELATED,ESTABLISHED -j ACCEPT
  iptables -C INPUT -p udp --dport "$UDP_PORT" -j ACCEPT 2>/dev/null \
    || iptables -A INPUT -p udp --dport "$UDP_PORT" -j ACCEPT
fi

echo "Server firewall/NAT ready."
