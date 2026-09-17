"""VPN client: connect to server UDP peer, forward TUN <-> UDP."""

from __future__ import annotations

import argparse
import logging
import signal
import sys
import threading

from .stats import TunnelStats
from .tun import configure_iface, open_tun
from .tunnel import Tunnel, make_udp_socket

log = logging.getLogger("vpn.client")


def parse_args(argv=None):
    p = argparse.ArgumentParser(description="User-space VPN tunnel client")
    p.add_argument("--server", required=True, help="Server host/IP")
    p.add_argument("--port", type=int, default=51820, help="Server UDP port")
    p.add_argument("--bind", default="0.0.0.0", help="Local UDP bind address")
    p.add_argument("--local-port", type=int, default=0, help="Local UDP port (0=ephemeral)")
    p.add_argument("--tun", default="vpn0", help="TUN interface name")
    p.add_argument("--addr", default="10.8.0.2", help="TUN IPv4 address")
    p.add_argument("--prefix", type=int, default=24, help="TUN prefix length")
    p.add_argument("--mtu", type=int, default=1400, help="TUN MTU")
    p.add_argument("--route", action="append", default=[], help="Extra route via TUN (CIDR)")
    p.add_argument("--stats-interval", type=float, default=2.0)
    p.add_argument("-v", "--verbose", action="store_true")
    return p.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    tun = open_tun(args.tun)
    configure_iface(tun.name, args.addr, args.prefix, args.mtu, peer="10.8.0.1")

    import subprocess

    for cidr in args.route:
        subprocess.run(
            ["ip", "route", "replace", cidr, "dev", tun.name],
            check=True,
            capture_output=True,
            text=True,
        )

    sock = make_udp_socket((args.bind, args.local_port))
    peer = (args.server, args.port)
    stats = TunnelStats()
    tunnel = Tunnel(tun=tun, sock=sock, peer=peer, stats=stats)

    # Immediate keepalive so server learns the client before traffic
    from . import protocol

    sock.sendto(protocol.pack(b"", 0, protocol.FLAG_KEEPALIVE), peer)

    stop = threading.Event()

    def _stop(*_):
        stop.set()
        tunnel.stop()

    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)

    def _stats_loop():
        while not stop.wait(args.stats_interval):
            log.info("stats %s", stats.format_line())

    threading.Thread(target=_stats_loop, daemon=True).start()
    log.info(
        "client peer %s:%s tun=%s addr=%s/%s mtu=%s",
        args.server,
        args.port,
        tun.name,
        args.addr,
        args.prefix,
        args.mtu,
    )
    try:
        tunnel.run(stop_event=stop)
    finally:
        snap = stats.snapshot()
        log.info(
            "final: packets_in=%s packets_out=%s mbps_in=%.2f mbps_out=%.2f",
            snap["packets_in"],
            snap["packets_out"],
            snap["mbps_in"],
            snap["mbps_out"],
        )
        tun.close()
        sock.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
