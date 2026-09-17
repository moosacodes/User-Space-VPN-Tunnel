"""UDP framing for encapsulated IP packets."""

from __future__ import annotations

import struct
from typing import Optional, Tuple

MAGIC = 0x5650  # 'VP'
VERSION = 1
HEADER = struct.Struct("!HBBI")  # magic, version, flags, seq
HEADER_SIZE = HEADER.size

FLAG_DATA = 0x01
FLAG_KEEPALIVE = 0x02


def pack(payload: bytes, seq: int, flags: int = FLAG_DATA) -> bytes:
    return HEADER.pack(MAGIC, VERSION, flags, seq & 0xFFFFFFFF) + payload


def unpack(datagram: bytes) -> Optional[Tuple[int, int, bytes]]:
    """
    Return (flags, seq, payload) or None if the datagram is not ours.
    """
    if len(datagram) < HEADER_SIZE:
        return None
    magic, version, flags, seq = HEADER.unpack_from(datagram)
    if magic != MAGIC or version != VERSION:
        return None
    return flags, seq, datagram[HEADER_SIZE:]
