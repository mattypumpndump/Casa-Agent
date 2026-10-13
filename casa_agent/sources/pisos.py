"""pisos.com scraper (rent + buy). No API key needed, BUT pisos.com blocks
plain HTTP clients from many networks (returns a challenge page). If this
source keeps failing with "blocked", set CASA_BROWSER_FALLBACK=1 to fetch
pages through a real headless Chromium via Playwright (pip install playwright
&& playwright install chromium).

Search pages: https://www.pisos.com/alquiler/pisos-madrid_capital/
              https://www.pisos.com/venta/pisos-madrid_capital/
Listing links: /alquilar/piso-madrid_capital_centro...-51234567/
               /comprar/piso-...-51234567/
Card text: "Piso en Calle ... 3 habs. 2 baños 106 m² ... 2.850 €/mes"
"""
from __future__ import annotations

import logging
import os
import re

from ..models import Listing, Operation, PropertyType, SearchParams
from ._scrape import euro, fetch_html, first_float, first_int, listing_cards
from .base import Source, SourceError

log = logging.getLogger(__name__)

_HREF = r"/(?P<op>alquilar|comprar)/(?P<slug>[a-z0-9_-]+?)-(?P<id>\d{6,12})/"
_CITY_SLUG = {"madrid": "madrid_capital", "barcelona": "barcelona_capital", "valencia": "valencia_capital",
              "sevilla": "sevilla_capital", "malaga": "malaga_capital"}


async def _fetch_with_browser(url: str) -> str:
    try:
        from playwright.async_api import async_playwright
    except ImportError as exc:
        raise SourceError("pisos: Playwright not installed (pip install playwright && playwright install chromium)") from exc
    async with async_playwright() as p:
        b = await p.chromium.launch()
        pg = await b.new_page()
        await pg.goto(url, wait_until="domcontentloaded", timeout=30000)
        await pg.wait_for_timeout(1500)
        html = await pg.content()
        await b.close()
    return html


class PisosSource(Source):
    name = "pisos"

    def _url(self, params: SearchParams) -> str:
        slug = _CITY_SLUG.get(params.city.lower(), params.city.lower() + "_capital")
        op = "alquiler" if params.operation == Operation.RENT else "venta"
        return f"https://www.pisos.com/{op}/pisos-{slug}/"

    async def search(self, params: SearchParams) -> list[Listing]:
        url = self._url(params)
        if os.getenv("CASA_BROWSER_FALLBACK") == "1":
            html = await _fetch_with_browser(url)
        else:
            html = await fetch_html(url, self.name)
        cards = listing_cards(html, _HREF)
        if not cards:
            raise SourceError("pisos: page loaded but no listings found — likely a bot challenge; try CASA_BROWSER_FALLBACK=1")
        out = []
        for href, text in cards:
            try:
                l = self._parse(href, text, params)
                if l:
                    out.append(l)
            except Exception as exc:  # noqa: BLE001
                log.debug("pisos: skip card: %s", exc)
        return out

    def _parse(self, href: str, text: str, params: SearchParams) -> Listing | None:
        m = re.search(_HREF, href)
        pid, slug = m.group("id"), m.group("slug")
        price = euro(text)
        if not price:
            return None
        size = first_float(r"(\d+(?:[.,]\d+)?)\s*m[²2]", text)
        beds = first_int(r"(\d+)\s*hab", text)
        baths = first_int(r"(\d+)\s*baño", text)
        low = text.lower()
        if slug.startswith("atico"):
            ptype = PropertyType.PENTHOUSE
        elif slug.startswith(("casa", "chalet")):
            ptype = PropertyType.HOUSE
        elif slug.startswith("estudio"):
            ptype = PropertyType.STUDIO
        elif slug.startswith("duplex"):
            ptype = PropertyType.DUPLEX
        else:
            ptype = PropertyType.FLAT
        tm = re.match(r"(.{8,120}?)(?:\s+\d+\s*hab|\s+\d+\s*m[²2]|\s+\d[\d.]*\s*€)", text)
        title = tm.group(1).strip() if tm else slug.replace("_", " ").replace("-", " ").capitalize()
        parts = slug.split("_")
        hood = parts[-1].replace("-", " ").title() if len(parts) > 2 else ""
        return Listing(
            id=f"pisos:{pid}",
            source=self.name,
            url=href if href.startswith("http") else "https://www.pisos.com" + href,
            operation=params.operation,
            property_type=ptype,
            title=title,
            description=text[:400],
            price=price,
            size_m2=size or 0.0,
            bedrooms=beds if beds is not None else (0 if ptype == PropertyType.STUDIO else 1),
            bathrooms=baths or 1,
            city=params.city,
            neighborhood=hood,
            has_elevator=True if "ascensor" in low else None,
            has_terrace=True if "terraza" in low else None,
            has_parking=True if ("garaje" in low or "parking" in low) else None,
        )
