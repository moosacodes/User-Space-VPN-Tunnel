# User-Space VPN Tunnel

Python user-space VPN that moves raw IP packets between Linux hosts over **TUN**
devices encapsulated in **UDP**. Built to sustain **10K+ packets** and
**20+ Mbps**, with Wireshark/tcpdump workflows for routing, NAT, and firewall
failures.

## Architecture

```
App / kernel routing
        │
   TUN vpn0 (raw IPv4)
        │
  vpn.server / vpn.client   ← user space
        │
   UDP :51820  (framed: magic|ver|flags|seq|payload)
        │
     peer host
```

- `vpn/tun.py` — open `/dev/net/tun` (`IFF_TUN | IFF_NO_PI`)
- `vpn/protocol.py` — lightweight UDP framing
- `vpn/tunnel.py` — select-loop forwarder with large socket buffers
- `vpn/server.py` / `vpn/client.py` — CLI endpoints

## Quick start (two Linux hosts)

**Server (10.8.0.1):**

```bash
sudo python3 -m vpn.server --bind 0.0.0.0 --port 51820 --addr 10.8.0.1
sudo WAN_IF=eth0 ./scripts/setup_server_nat.sh
```

**Client (10.8.0.2):**

```bash
sudo python3 -m vpn.client --server SERVER_PUBLIC_IP --port 51820 --addr 10.8.0.2
sudo ./scripts/setup_client_routes.sh
ping -c 3 10.8.0.1
```

## Prove the metrics

### Userspace UDP path (no root)

```bash
python3 tools/bench.py --mode udp-loop --duration 8 --target-mbps 25 --min-packets 10000 --min-mbps 20
```

### Real TUN path (two namespaces on one machine)

```bash
sudo ./scripts/bench_netns.sh 10 20 10000
```

### Unit test gate

```bash
python3 -m unittest tests.test_tunnel -v
```

## Network tests & packet tracing

```bash
# 20 automated checks (routing / ICMP / MTU / UDP / tooling)
PEER=10.8.0.1 SELF=10.8.0.2 ./scripts/run_network_tests.sh

# PCAP pair for Wireshark
sudo ./scripts/capture_flows.sh
```

See [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md) for the **6** routing,
NAT, and firewall failures resolved by comparing WAN (outer UDP) vs TUN (inner
IP) captures.

## Resume bullets (backed by this repo)

- Routed **10K+** IP packets between 2 Linux hosts at **20+ Mbps** via user-space
  TUN + UDP forwarding (`tools/bench.py`, `scripts/bench_netns.sh`).
- Resolved **6/6** routing, NAT, and firewall failures by tracing packet flows
  with Wireshark/tcpdump across **15+** network tests
  (`docs/TROUBLESHOOTING.md`, `scripts/run_network_tests.sh`).

## Requirements

- Linux with `/dev/net/tun` and `CAP_NET_ADMIN` (for real TUN)
- Python 3.9+
- `iproute2`, `tcpdump` (optional: `iptables`/`nftables`, Wireshark)

## License

MIT
