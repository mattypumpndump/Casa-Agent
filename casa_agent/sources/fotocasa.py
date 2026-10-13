"""Fotocasa scraper (no official API).

Fotocasa renders its search results from a JSON blob embedded in the page
(`window.__INITIAL_PROPS__`). We fetch the page, pull that JSON and map it
to Listings. This is inherently fragile: the site may change its markup or
block automated requests. On any failure we raise SourceError so the rest
of the pipeline keeps working with the other sources.

Check Fotocasa's terms of service before using this against the live site,
and keep request volume low.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import date

import httpx
from bs4 import BeautifulSoup

from .. import config
from ..models import Listing, Operation, PropertyType, SearchParams
from .base import Source, SourceError

log = logging.getLogger(__name__)

_CITY_SLUG = {
    "madrid": "madrid-capital",
    "barcelona": "barcelona-capital",
    "valencia": "valencia-capital",
    "sevilla": "sevilla-capital",
    "malaga": "malaga-capital",
}

_TYPE_MAP = {
    1: PropertyType.HOUSE,
    2: PropertyType.FLAT,
    3: PropertyType.FLAT,  # apartment
    6: PropertyType.STUDIO,
    8: PropertyType.PENTHOUSE,
    9: PropertyType.DUPLEX,
}


class FotocasaSource(Source):
    name = "fotocasa"

    def _url(self, params: SearchParams) -> str:
        slug = _CITY_SLUG.get(params.city.lower(), params.city.lower() + "-capital")
        op = "alquiler" if params.operation == Operation.RENT else "comprar"
        url = f"https://www.fotocasa.es/es/{op}/viviendas/{slug}/todas-las-zonas/l"
        q = []
        if params.max_price:
            q.append(f"maxPrice={int(params.max_price)}")
        if params.min_price:
            q.append(f"minPrice={int(params.min_price)}")
        if params.min_bedrooms:
            q.append(f"minRooms={params.min_bedrooms}")
        if params.min_size_m2:
            q.append(f"minSurface={int(params.min_size_m2)}")
        return url + ("?" + "&".join(q) if q else "")

    async def search(self, params: SearchParams) -> list[Listing]:
        url = self._url(params)
        headers = {
            "User-Agent": config.USER_AGENT,
            "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
            "Accept": "text/html,application/xhtml+xml",
        }
        try:
            async with httpx.AsyncClient(timeout=config.SCRAPE_TIMEOUT, follow_redirects=True) as client:
                r = await client.get(url, headers=headers)
        except httpx.HTTPError as exc:
            raise SourceError(f"Fotocasa request failed: {exc}") from exc
        if r.status_code in (403, 429):
            raise SourceError(f"Fotocasa blocked the request (HTTP {r.status_code})")
        if r.status_code != 200:
            raise SourceError(f"Fotocasa returned HTTP {r.status_code}")

        data = self._extract_initial_props(r.text)
        if data is None:
            raise SourceError("Fotocasa page structure not recognised (no __INITIAL_PROPS__)")

        items = self._find_realestates(data)
        listings = []
        for it in items:
            try:
                listings.append(self._to_listing(it, params))
            except Exception as exc:  # one bad card shouldn't kill the batch
                log.debug("Skipping Fotocasa item: %s", exc)
        return listings

    @staticmethod
    def _extract_initial_props(html: str) -> dict | None:
        soup = BeautifulSoup(html, "html.parser")
        for script in soup.find_all("script"):
            txt = script.string or ""
            m = re.search(r"window\.__INITIAL_PROPS__\s*=\s*JSON\.parse\((\"(?:[^\"\\]|\\.)*\")\)", txt)
            if m:
                try:
                    return json.loads(json.loads(m.group(1)))
                except json.JSONDecodeError:
                    return None
            m = re.search(r"window\.__INITIAL_PROPS__\s*=\s*(\{.*?\});?\s*$", txt, re.S)
            if m:
                try:
                    return json.loads(m.group(1))
                except json.JSONDecodeError:
                    return None
        return None

    @staticmethod
    def _find_realestates(data) -> list[dict]:
        """Depth-first search for a list of dicts that look like property cards."""
        stack = [data]
        while stack:
            node = stack.pop()
            if isinstance(node, dict):
                for k, v in node.items():
                    if k in ("realEstates", "items") and isinstance(v, list) and v and isinstance(v[0], dict) and "id" in v[0]:
                        return v
                    stack.append(v)
            elif isinstance(node, list):
                stack.extend(node)
        return []

    def _to_listing(self, it: dict, params: SearchParams) -> Listing:
        features = {f.get("key"): f.get("value") for f in it.get("features", []) if isinstance(f, dict)}
        trans = (it.get("transactions") or [{}])[0]
        price = trans.get("value", [None])[0] if isinstance(trans.get("value"), list) else trans.get("value")
        addr = it.get("address", {}) or {}
        coords = addr.get("coordinates", {}) or {}
        pid = str(it["id"])
        return Listing(
            id=f"fotocasa:{pid}",
            source=self.name,
            url=f"https://www.fotocasa.es{it.get('detail', {}).get('es-ES', '')}" if it.get("detail") else f"https://www.fotocasa.es/es/vivienda/{pid}",
            operation=params.operation,
            property_type=_TYPE_MAP.get(it.get("typeId"), PropertyType.OTHER),
            title=it.get("title", "") or "",
            description=it.get("description", "") or "",
            price=float(price or 0),
            size_m2=float(features.get("surface", 0) or 0),
            bedrooms=int(features.get("rooms", 0) or 0),
            bathrooms=int(features.get("bathrooms", 0) or 0),
            floor=_safe_int(features.get("floor")),
            city=addr.get("municipality", params.city) or params.city,
            district=addr.get("district", "") or "",
            neighborhood=addr.get("neighbourhood", "") or "",
            address=addr.get("ubication", "") or "",
            lat=coords.get("latitude"),
            lon=coords.get("longitude"),
            has_elevator=_safe_bool(features.get("elevator")),
            has_terrace=_safe_bool(features.get("terrace")),
            has_parking=_safe_bool(features.get("parking")),
            has_air_conditioning=_safe_bool(features.get("air_conditioner")),
            furnished=_safe_bool(features.get("furnished")),
            energy_rating=(it.get("energyCertificate") or {}).get("rating"),
            photos=[m.get("src") for m in it.get("multimedia", []) if isinstance(m, dict) and m.get("src")][:6],
            published=_safe_date(it.get("date")),
        )


def _safe_int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _safe_bool(v):
    if v is None:
        return None
    if isinstance(v, bool):
        return v
    return str(v).lower() in ("1", "true", "yes", "si", "sí")


def _safe_date(v):
    if not v:
        return None
    try:
        return date.fromisoformat(str(v)[:10])
    except ValueError:
        return None
