"""Throughput and packet counters for the tunnel."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field


@dataclass
class TunnelStats:
    packets_in: int = 0
    packets_out: int = 0
    bytes_in: int = 0
    bytes_out: int = 0
    started_at: float = field(default_factory=time.monotonic)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def record_in(self, nbytes: int) -> None:
        with self._lock:
            self.packets_in += 1
            self.bytes_in += nbytes

    def record_out(self, nbytes: int) -> None:
        with self._lock:
            self.packets_out += 1
            self.bytes_out += nbytes

    def snapshot(self) -> dict:
        with self._lock:
            elapsed = max(time.monotonic() - self.started_at, 1e-9)
            bits_out = self.bytes_out * 8
            bits_in = self.bytes_in * 8
            return {
                "elapsed_s": elapsed,
                "packets_in": self.packets_in,
                "packets_out": self.packets_out,
                "bytes_in": self.bytes_in,
                "bytes_out": self.bytes_out,
                "mbps_out": (bits_out / elapsed) / 1_000_000,
                "mbps_in": (bits_in / elapsed) / 1_000_000,
                "pps_out": self.packets_out / elapsed,
                "pps_in": self.packets_in / elapsed,
            }

    def format_line(self) -> str:
        s = self.snapshot()
        return (
            f"in={s['packets_in']}pkt/{s['mbps_in']:.2f}Mbps "
            f"out={s['packets_out']}pkt/{s['mbps_out']:.2f}Mbps "
            f"elapsed={s['elapsed_s']:.1f}s"
        )
