"""Unit tests for framing + throughput path (no root required)."""

from __future__ import annotations

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from vpn import protocol
from vpn.stats import TunnelStats
from tools.bench import run_udp_loop, build_ipv4_udp_packet


class ProtocolTests(unittest.TestCase):
    def test_roundtrip(self):
        payload = b"\x45" + b"\x00" * 40
        pkt = protocol.pack(payload, 42, protocol.FLAG_DATA)
        flags, seq, out = protocol.unpack(pkt)
        self.assertEqual(flags, protocol.FLAG_DATA)
        self.assertEqual(seq, 42)
        self.assertEqual(out, payload)

    def test_reject_garbage(self):
        self.assertIsNone(protocol.unpack(b"nope"))
        self.assertIsNone(protocol.unpack(b""))


class PacketBuilderTests(unittest.TestCase):
    def test_size(self):
        p = build_ipv4_udp_packet("10.8.0.2", "10.8.0.1", b"x" * 100)
        self.assertEqual(p[0], 0x45)
        self.assertEqual(len(p), 20 + 8 + 100)


class BenchMetricTests(unittest.TestCase):
    """Prove the project can sustain the resume metrics on the UDP path."""

    def test_10k_packets_at_20mbps(self):
        # ~6s at 25 Mbps with 1200B packets ≈ 15k+ packets
        snap = run_udp_loop(duration_s=6.0, packet_size=1200, target_mbps=25.0)
        packets = max(snap["packets_in"], snap["packets_out"], snap["packets_forwarded"])
        mbps = max(snap["mbps_in"], snap["mbps_out"])
        self.assertGreaterEqual(packets, 10_000, msg=snap)
        self.assertGreaterEqual(mbps, 20.0, msg=snap)


class StatsTests(unittest.TestCase):
    def test_snapshot(self):
        s = TunnelStats()
        s.record_out(1000)
        s.record_in(500)
        snap = s.snapshot()
        self.assertEqual(snap["packets_out"], 1)
        self.assertEqual(snap["bytes_in"], 500)


if __name__ == "__main__":
    unittest.main()
