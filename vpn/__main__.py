"""python -m vpn server|client ..."""

from __future__ import annotations

import sys


def main() -> None:
    if len(sys.argv) < 2 or sys.argv[1] not in {"server", "client"}:
        print("usage: python -m vpn {server|client} [args...]", file=sys.stderr)
        sys.exit(2)
    role = sys.argv.pop(1)
    if role == "server":
        from .server import main as run

        sys.exit(run())
    from .client import main as run

    sys.exit(run())


if __name__ == "__main__":
    main()
