# Troubleshooting: routing, NAT, and firewall

Six failures that blocked the tunnel in practice — each resolved by tracing
outer UDP vs inner IP with **tcpdump/Wireshark** across the automated suite in
`scripts/run_network_tests.sh` (20 checks) and ad-hoc captures
(`scripts/capture_flows.sh`).

Capture both sides, then open in Wireshark:

```bash
sudo ./scripts/capture_flows.sh
# Wireshark: wan_*.pcap  and  tun_*.pcap
```

Useful display filters:

| Filter | Meaning |
|--------|---------|
| `udp.port == 51820` | Outer tunnel datagrams |
| `ip.addr == 10.8.0.0/24` | Overlay / inner addresses |
| `icmp` | Ping path |
| `tcp.flags.syn==1 && tcp.flags.ack==0` | Outbound TCP handshake |

---

## Failure 1 — Outer UDP blocked on server INPUT

**Symptom:** Client TX counters climb; server never learns a peer. WAN PCAP on
client shows UDP 51820 leaving; server WAN PCAP shows nothing arriving (or
arriving then silent drop).

**Trace:** Compare client `wan_*.pcap` vs server `wan_*.pcap` with
`udp.port == 51820`.

**Fix:** Allow the tunnel port before blaming TUN:

```bash
sudo iptables -A INPUT -p udp --dport 51820 -j ACCEPT
# or
sudo ./scripts/setup_server_nat.sh
```

**Test:** T08 / T15 / T18–T19 in `run_network_tests.sh`.

---

## Failure 2 — Missing overlay route (traffic never hits TUN)

**Symptom:** `ping 10.8.0.1` fails immediately (`Network unreachable`). No
frames on `tun0` in tcpdump.

**Trace:** `ip route get 10.8.0.1` and Wireshark on TUN — empty capture while
WAN is idle.

**Fix:**

```bash
sudo ip route replace 10.8.0.1/32 dev vpn0
# or
sudo TUN_IF=vpn0 ./scripts/setup_client_routes.sh
```

**Test:** T05, T06.

---

## Failure 3 — FORWARD chain drops east-west / internet egress

**Symptom:** Overlay ping (10.8.0.1 ↔ 10.8.0.2) works; browsing via NAT fails.
TUN PCAP shows inner packets leaving the client; server TUN shows them arrive;
WAN on server never sees masqueraded traffic.

**Trace:** Three-point capture — client TUN, server TUN, server WAN. Inner IP
present, post-NAT public IP absent ⇒ filter forward drop.

**Fix:**

```bash
sudo iptables -A FORWARD -i vpn0 -o "$WAN_IF" -j ACCEPT
sudo iptables -A FORWARD -i "$WAN_IF" -o vpn0 -m state --state RELATED,ESTABLISHED -j ACCEPT
sudo ./scripts/setup_server_nat.sh
```

**Test:** T09, T17, plus manual curl via tunnel after NAT.

---

## Failure 4 — No MASQUERADE / SNAT for overlay clients

**Symptom:** Forward path accepts packets; replies never return. Server WAN
PCAP shows packets leaving with source `10.8.0.2` (private) onto the internet.

**Trace:** Wireshark on WAN: `ip.src == 10.8.0.2`. Those must be rewritten.

**Fix:**

```bash
sudo iptables -t nat -A POSTROUTING -s 10.8.0.0/24 -o "$WAN_IF" -j MASQUERADE
```

**Test:** T17; confirm with `iptables -t nat -L -n -v` counters incrementing.

---

## Failure 5 — Reverse-path filtering (`rp_filter`) drops return traffic

**Symptom:** Asymmetric routing after full-tunnel or policy routes. Outbound
SYN visible; SYN-ACK arrives on WAN then disappears before TUN.

**Trace:** WAN PCAP has return packets; TUN PCAP does not. Kernel logs may show
`rpfilter` drops (`dmesg` / `nft` counters).

**Fix:**

```bash
sudo sysctl -w net.ipv4.conf.all.rp_filter=0
sudo sysctl -w net.ipv4.conf.vpn0.rp_filter=0
```

(Prefer `=2` loose mode if your distro policy allows.)

**Test:** T16; T13 TCP reachability.

---

## Failure 6 — MTU / DF black hole (TCP stalls, ping -s large fails)

**Symptom:** Small pings succeed; HTTP hangs after handshake. Wireshark shows
retransmits; large ICMP with DF never answered.

**Trace:** TUN PCAP — successful 64-byte ICMP, failed 1400-byte ICMP.
Outer UDP size ≈ inner + header; if inner MTU is 1500, outer may fragment or
drop on path.

**Fix:** Lower TUN MTU (default in this project: **1400**):

```bash
sudo ip link set dev vpn0 mtu 1400
# restart vpn.server / vpn.client with --mtu 1400
```

**Test:** T04, T11, T12.

---

## Suggested 15+ test campaign

Run after each firewall/NAT change:

```bash
PEER=10.8.0.1 SELF=10.8.0.2 ./scripts/run_network_tests.sh
```

The script executes **20** checks (TUN state, routing, ICMP, MTU, UDP blast,
firewall tooling, tcpdump filters, sustained ping). Keep PCAPs under
`captures/` for write-ups.
