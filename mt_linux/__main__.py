from __future__ import annotations

import asyncio

from mt_linux.daemon import run_daemon


def main() -> None:
    asyncio.run(run_daemon())


if __name__ == "__main__":
    main()
