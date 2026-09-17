"""VPN server: wait for client UDP, forward TUN <-> UDP."""

from __future__ import annotations

import argparse
import logging
import signal
import sys
import threading

from .stats import TunnelStats
from .tun import configure_iface, open_tun
from .tunnel import Tunnel, make_udp_socket

log = logging.getLogger("vpn.server")


def parse_args(argv=None):
    p = argparse.ArgumentParser(description="User-space VPN tunnel server")
    p.add_argument("--bind", default="0.0.0.0", help="UDP bind address")
    p.add_argument("--port", type=int, default=51820, help="UDP listen port")
    p.add_argument("--tun", default="vpn0", help="TUN interface name")
    p.add_argument("--addr", default="10.8.0.1", help="TUN IPv4 address")
    p.add_argument("--prefix", type=int, default=24, help="TUN prefix length")
    p.add_argument("--mtu", type=int, default=1400, help="TUN MTU")
    p.add_argument("--client-net", default="10.8.0.0/24", help="Client overlay CIDR (for docs/NAT)")
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
    configure_iface(tun.name, args.addr, args.prefix, args.mtu)
    sock = make_udp_socket((args.bind, args.port))
    stats = TunnelStats()
    tunnel = Tunnel(tun=tun, sock=sock, peer=None, stats=stats)

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
        "server listening UDP %s:%s tun=%s addr=%s/%s mtu=%s",
        args.bind,
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
