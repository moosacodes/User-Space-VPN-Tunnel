"""Bidirectional TUN <-> UDP forwarding loop."""

from __future__ import annotations

import logging
import select
import socket
import time
from typing import Optional, Tuple

from . import protocol
from .stats import TunnelStats
from .tun import TunDevice

log = logging.getLogger("vpn.tunnel")


class Tunnel:
    """
    Forward raw IP packets between a TUN device and a UDP peer.

    Designed for high throughput: large socket buffers, batch-friendly
    select loop, and minimal per-packet allocation overhead.
    """

    def __init__(
        self,
        tun: TunDevice,
        sock: socket.socket,
        peer: Optional[Tuple[str, int]] = None,
        stats: Optional[TunnelStats] = None,
        keepalive_s: float = 5.0,
    ) -> None:
        self.tun = tun
        self.sock = sock
        self.peer = peer
        self.stats = stats or TunnelStats()
        self.keepalive_s = keepalive_s
        self._seq = 0
        self._running = False
        self._last_peer_activity = time.monotonic()
        self._last_keepalive_sent = 0.0

    def _next_seq(self) -> int:
        self._seq = (self._seq + 1) & 0xFFFFFFFF
        return self._seq

    def _send_udp(self, payload: bytes, flags: int = protocol.FLAG_DATA) -> None:
        if self.peer is None:
            return
        datagram = protocol.pack(payload, self._next_seq(), flags)
        self.sock.sendto(datagram, self.peer)
        if flags & protocol.FLAG_DATA:
            self.stats.record_out(len(payload))

    def _handle_tun(self) -> None:
        # Drain several packets per wake to reduce syscall/select overhead
        for _ in range(64):
            try:
                packet = self.tun.read()
            except BlockingIOError:
                break
            if not packet:
                break
            self._send_udp(packet)

    def _handle_udp(self) -> None:
        for _ in range(64):
            try:
                data, addr = self.sock.recvfrom(65535)
            except BlockingIOError:
                break
            parsed = protocol.unpack(data)
            if parsed is None:
                continue
            flags, _seq, payload = parsed
            # Learn / lock peer address (server accepts first client)
            if self.peer is None:
                self.peer = addr
                log.info("peer learned: %s:%s", addr[0], addr[1])
            elif addr != self.peer:
                # Ignore stray senders once peer is fixed
                continue

            self._last_peer_activity = time.monotonic()
            if flags & protocol.FLAG_KEEPALIVE:
                continue
            if not payload:
                continue
            try:
                self.tun.write(payload)
            except BlockingIOError:
                # TUN backpressure — drop this packet
                continue
            self.stats.record_in(len(payload))

    def _maybe_keepalive(self, now: float) -> None:
        if self.peer is None:
            return
        if now - self._last_peer_activity < self.keepalive_s:
            return
        if now - self._last_keepalive_sent < self.keepalive_s:
            return
        self._send_udp(b"", flags=protocol.FLAG_KEEPALIVE)
        self._last_keepalive_sent = now

    def run(self, stop_event=None) -> None:
        self._running = True
        self.sock.setblocking(False)
        log.info("tunnel running on %s -> peer %s", self.tun.name, self.peer)
        try:
            while self._running:
                if stop_event is not None and stop_event.is_set():
                    break
                rlist, _, _ = select.select([self.tun, self.sock], [], [], 0.5)
                if self.tun in rlist:
                    self._handle_tun()
                if self.sock in rlist:
                    self._handle_udp()
                self._maybe_keepalive(time.monotonic())
        finally:
            self._running = False
            log.info("tunnel stopped: %s", self.stats.format_line())

    def stop(self) -> None:
        self._running = False


def make_udp_socket(bind: Tuple[str, int], rcvbuf: int = 4 * 1024 * 1024) -> socket.socket:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    # Large buffers help sustain 20+ Mbps under bursty traffic
    for opt in (socket.SO_RCVBUF, socket.SO_SNDBUF):
        try:
            sock.setsockopt(socket.SOL_SOCKET, opt, rcvbuf)
        except OSError:
            pass
    sock.bind(bind)
    return sock
