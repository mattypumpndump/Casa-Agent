"""Diagnostic: query every source and report what works from this machine.

    python -m casa_agent.check            # rent, Madrid, all known sources
    python -m casa_agent.check buy        # buy instead of rent
"""
from __future__ import annotations

import asyncio
import sys
import time

from .models import Operation, SearchParams
from .sources import SourceError, get_sources

ALL = ["spotahome", "habitaclia", "pisos", "fotocasa", "idealista", "demo"]


async def main() -> None:
    op = Operation.BUY if len(sys.argv) > 1 and sys.argv[1].lower().startswith("b") else Operation.RENT
    params = SearchParams(operation=op, city="Madrid")
    print(f"Testing sources for {op.value} in Madrid…\n")
    ok_real = 0
    for src in get_sources(ALL):
        t = time.time()
        try:
            ls = await src.search(params)
            dt = time.time() - t
            sample = ls[0] if ls else None
            print(f"✅ {src.name:<11} {len(ls):>4} listings in {dt:4.1f}s"
                  + (f"   e.g. {sample.key_facts()}  →  {sample.url}" if sample else ""))
            if ls and not src.name.startswith("demo"):
                ok_real += 1
        except SourceError as exc:
            print(f"❌ {src.name:<11} {exc}")
        except Exception as exc:  # noqa: BLE001
            print(f"💥 {src.name:<11} crashed: {type(exc).__name__}: {exc}")
    print()
    if ok_real:
        print(f"{ok_real} real portal(s) work. Put them in CASA_SOURCES in .env and demo data will not be shown.")
    else:
        print("No real portal worked from this machine. Common causes: blocked network/VPN, portal changed its page, "
              "or (for idealista) missing API keys. Paste this output to get the scraper fixed.")


if __name__ == "__main__":
    asyncio.run(main())
