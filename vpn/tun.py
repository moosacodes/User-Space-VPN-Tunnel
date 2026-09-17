"""Linux TUN device helpers (IFF_TUN | IFF_NO_PI)."""

from __future__ import annotations

import fcntl
import os
import struct
from dataclasses import dataclass
from typing import Optional

# linux/if_tun.h
TUNSETIFF = 0x400454CA
IFF_TUN = 0x0001
IFF_NO_PI = 0x1000
IFNAMSIZ = 16


@dataclass
class TunDevice:
    """Opened TUN interface file descriptor and name."""

    fd: int
    name: str

    def read(self, bufsize: int = 65535) -> bytes:
        return os.read(self.fd, bufsize)

    def write(self, data: bytes) -> int:
        return os.write(self.fd, data)

    def fileno(self) -> int:
        return self.fd

    def close(self) -> None:
        if self.fd >= 0:
            os.close(self.fd)
            self.fd = -1


def open_tun(name: str = "vpn0") -> TunDevice:
    """
    Open /dev/net/tun and attach a named TUN interface.

    Requires CAP_NET_ADMIN (typically root). Packets are raw IP (no PI header).
    """
    if not name or len(name.encode()) >= IFNAMSIZ:
        raise ValueError(f"TUN name must be 1..{IFNAMSIZ - 1} bytes: {name!r}")

    fd = os.open("/dev/net/tun", os.O_RDWR)
    # struct ifreq: ifr_name[IFNAMSIZ] + ifr_flags (short) + padding
    ifr = struct.pack("16sH", name.encode("ascii"), IFF_TUN | IFF_NO_PI)
    try:
        result = fcntl.ioctl(fd, TUNSETIFF, ifr)
    except OSError:
        os.close(fd)
        raise

    real_name = result[:IFNAMSIZ].split(b"\x00", 1)[0].decode("ascii")
    # Non-blocking for select/poll loops
    flags = fcntl.fcntl(fd, fcntl.F_GETFL)
    fcntl.fcntl(fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)
    return TunDevice(fd=fd, name=real_name)


def configure_iface(
    name: str,
    address: str,
    prefix: int = 24,
    mtu: int = 1400,
    peer: Optional[str] = None,
) -> None:
    """Bring up the TUN iface with address/MTU using iproute2."""
    import subprocess

    cmds = [
        ["ip", "link", "set", "dev", name, "mtu", str(mtu), "up"],
        ["ip", "addr", "add", f"{address}/{prefix}", "dev", name],
    ]
    if peer:
        # Point-to-point style; useful for /30 style tunnels
        cmds.append(["ip", "route", "replace", f"{peer}/32", "dev", name])

    for cmd in cmds:
        subprocess.run(cmd, check=True, capture_output=True, text=True)
