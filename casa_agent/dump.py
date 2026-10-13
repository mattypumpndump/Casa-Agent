"""Save the raw HTML a portal serves to this machine, so a scraper can be fixed.

    python -m casa_agent.dump habitaclia      → debug/habitaclia.html
    python -m casa_agent.dump spotahome fotocasa pisos
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from .models import SearchParams
from .sources._scrape import fetch_html

URLS = {
    "spotahome": "https://www.spotahome.com/s/madrid--spain?type[]=apartments&type[]=studios",
    "habitaclia": "https://www.habitaclia.com/alquiler-madrid.htm",
    "fotocasa": "https://www.fotocasa.es/es/alquiler/viviendas/madrid-capital/todas-las-zonas/l",
    "pisos": "https://www.pisos.com/alquiler/pisos-madrid_capital/",
}


async def main() -> None:
    names = sys.argv[1:] or list(URLS)
    Path("debug").mkdir(exist_ok=True)
    for n in names:
        url = URLS.get(n)
        if not url:
            print(f"unknown source {n}"); continue
        try:
            html = await fetch_html(url, n)
            out = Path("debug") / f"{n}.html"
            out.write_text(html, encoding="utf-8")
            print(f"✅ {n}: saved {len(html):,} chars to {out}")
        except Exception as exc:  # noqa: BLE001
            print(f"❌ {n}: {exc}")


if __name__ == "__main__":
    asyncio.run(main())
