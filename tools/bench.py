"""
Throughput / packet-count benchmark for the user-space VPN.

Modes:
  udp-loop   – pure userspace UDP encapsulate/forward (no root / TUN)
  netns      – two Linux network namespaces + real TUN (requires root)

Targets: >= 10_000 IP packets and >= 20 Mbps sustained.
"""

from __future__ import annotations

import argparse
import os
import socket
import struct
import sys
import threading
import time
from typing import Tuple

# Allow `python -m tools.bench` from repo root
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from vpn import protocol  # noqa: E402
from vpn.stats import TunnelStats  # noqa: E402


def build_ipv4_udp_packet(
    src: str,
    dst: str,
    payload: bytes,
    src_port: int = 40000,
    dst_port: int = 40001,
    ident: int = 1,
) -> bytes:
    """Craft a minimal IPv4/UDP packet (checksums left 0 — fine for TUN load)."""

    def ip_to_bytes(ip: str) -> bytes:
        return socket.inet_aton(ip)

    udp_len = 8 + len(payload)
    udp = struct.pack("!HHHH", src_port, dst_port, udp_len, 0) + payload

    total_len = 20 + len(udp)
    # ver_ihl=0x45, tos=0, total_len, id, flags/frag=0, ttl=64, proto=17(UDP), checksum=0
    ip_header = struct.pack(
        "!BBHHHBBH4s4s",
        0x45,
        0,
        total_len,
        ident & 0xFFFF,
        0,
        64,
        17,
        0,
        ip_to_bytes(src),
        ip_to_bytes(dst),
    )
    return ip_header + udp


def run_udp_loop(
    duration_s: float,
    packet_size: int,
    target_mbps: float,
) -> dict:
    """
    Bidirectional-ish UDP tunnel path: sender -> 'server' forwarder -> receiver.

    Measures encapsulated IP payload bytes (same accounting as the real tunnel).
    """
    stats = TunnelStats()
    stop = threading.Event()

    srv = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    srv.bind(("127.0.0.1", 0))
    srv_port = srv.getsockname()[1]
    for opt in (socket.SO_RCVBUF, socket.SO_SNDBUF):
        srv.setsockopt(socket.SOL_SOCKET, opt, 8 * 1024 * 1024)

    rcv = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    rcv.bind(("127.0.0.1", 0))
    rcv_port = rcv.getsockname()[1]
    for opt in (socket.SO_RCVBUF, socket.SO_SNDBUF):
        rcv.setsockopt(socket.SOL_SOCKET, opt, 8 * 1024 * 1024)

    snd = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    for opt in (socket.SO_RCVBUF, socket.SO_SNDBUF):
        snd.setsockopt(socket.SOL_SOCKET, opt, 8 * 1024 * 1024)

    forwarded = {"n": 0, "bytes": 0}

    def forwarder():
        srv.settimeout(0.2)
        while not stop.is_set():
            try:
                data, addr = srv.recvfrom(65535)
            except socket.timeout:
                continue
            parsed = protocol.unpack(data)
            if not parsed:
                continue
            flags, seq, payload = parsed
            if flags & protocol.FLAG_DATA and payload:
                # Re-encapsulate toward receiver (server->client path)
                out = protocol.pack(payload, seq)
                srv.sendto(out, ("127.0.0.1", rcv_port))
                forwarded["n"] += 1
                forwarded["bytes"] += len(payload)
                stats.record_out(len(payload))

    def receiver():
        rcv.settimeout(0.2)
        while not stop.is_set():
            try:
                data, _ = rcv.recvfrom(65535)
            except socket.timeout:
                continue
            parsed = protocol.unpack(data)
            if not parsed:
                continue
            flags, _, payload = parsed
            if flags & protocol.FLAG_DATA and payload:
                stats.record_in(len(payload))

    t_fwd = threading.Thread(target=forwarder, daemon=True)
    t_rcv = threading.Thread(target=receiver, daemon=True)
    t_fwd.start()
    t_rcv.start()

    payload = os.urandom(max(packet_size - 28, 64))  # IP+UDP headers ~28
    # Pace to slightly above target so we clear 20 Mbps after overhead/scheduling
    bits_per_packet = packet_size * 8
    target_pps = (target_mbps * 1_000_000) / bits_per_packet
    interval = 1.0 / (target_pps * 1.15)  # 15% headroom

    seq = 0
    t0 = time.monotonic()
    next_t = t0
    sent = 0
    while time.monotonic() - t0 < duration_s:
        pkt = build_ipv4_udp_packet("10.8.0.2", "10.8.0.1", payload, ident=seq)
        datagram = protocol.pack(pkt, seq)
        snd.sendto(datagram, ("127.0.0.1", srv_port))
        sent += 1
        seq += 1
        next_t += interval
        sleep_for = next_t - time.monotonic()
        if sleep_for > 0:
            time.sleep(sleep_for)
        elif sleep_for < -0.05:
            # Fell behind — catch up without sleeping
            next_t = time.monotonic()

    # Drain
    time.sleep(0.5)
    stop.set()
    t_fwd.join(timeout=1)
    t_rcv.join(timeout=1)
    snd.close()
    srv.close()
    rcv.close()

    snap = stats.snapshot()
    snap["packets_sent"] = sent
    snap["packets_forwarded"] = forwarded["n"]
    snap["packet_size"] = packet_size
    snap["target_mbps"] = target_mbps
    return snap


def print_result(snap: dict, min_packets: int, min_mbps: float) -> int:
    mbps = max(snap["mbps_in"], snap["mbps_out"])
    packets = max(snap["packets_in"], snap["packets_out"], snap.get("packets_forwarded", 0))
    print("=== VPN Tunnel Benchmark ===")
    print(f"elapsed_s:         {snap['elapsed_s']:.2f}")
    print(f"packet_size:       {snap.get('packet_size', '?')}")
    print(f"packets_sent:      {snap.get('packets_sent', '?')}")
    print(f"packets_forwarded: {snap.get('packets_forwarded', packets)}")
    print(f"packets_in:        {snap['packets_in']}")
    print(f"packets_out:       {snap['packets_out']}")
    print(f"mbps_in:           {snap['mbps_in']:.2f}")
    print(f"mbps_out:          {snap['mbps_out']:.2f}")
    print(f"peak_mbps_used:    {mbps:.2f}")
    ok_pkt = packets >= min_packets
    ok_rate = mbps >= min_mbps
    print(f"PASS packets>={min_packets}: {ok_pkt} ({packets})")
    print(f"PASS mbps>={min_mbps}:       {ok_rate} ({mbps:.2f})")
    return 0 if (ok_pkt and ok_rate) else 1


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="VPN tunnel throughput benchmark")
    p.add_argument("--mode", choices=["udp-loop", "netns"], default="udp-loop")
    p.add_argument("--duration", type=float, default=8.0, help="Seconds of traffic")
    p.add_argument("--packet-size", type=int, default=1200, help="Approx IP packet size")
    p.add_argument("--target-mbps", type=float, default=25.0, help="Send pacing target")
    p.add_argument("--min-packets", type=int, default=10_000)
    p.add_argument("--min-mbps", type=float, default=20.0)
    args = p.parse_args(argv)

    if args.mode == "udp-loop":
        snap = run_udp_loop(args.duration, args.packet_size, args.target_mbps)
        return print_result(snap, args.min_packets, args.min_mbps)

    # netns mode delegates to shell script for real TUN path
    script = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "scripts",
        "bench_netns.sh",
    )
    if not os.path.exists(script):
        print("bench_netns.sh not found", file=sys.stderr)
        return 2
    return os.execv("/bin/bash", ["bash", script, str(args.duration), str(args.min_mbps), str(args.min_packets)])


if __name__ == "__main__":
    sys.exit(main())
