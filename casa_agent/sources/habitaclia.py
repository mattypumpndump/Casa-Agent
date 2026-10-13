"""Habitaclia scraper (rent + buy). No API key needed.

Search pages: https://www.habitaclia.com/alquiler-madrid.htm  (rent)
              https://www.habitaclia.com/viviendas-madrid.htm (buy)
              pagination: alquiler-madrid-2.htm, ...
Listing links: https://www.habitaclia.com/alquiler-piso-...-madrid-i16831000022808.htm
Card text: "Piso en alquiler en Embajadores ... Madrid - Embajadores-Lavapiés
            106m2 - 3 habitaciones - 2 baños - 26,89€/m2 ... 2.850 €"
"""
from __future__ import annotations

import logging
import re

from ..models import Listing, Operation, PropertyType, SearchParams
from ._scrape import euro, fetch_html, first_float, first_int, listing_cards
from .base import Source, SourceError

log = logging.getLogger(__name__)

_HREF = r"/(?P<op>alquiler|comprar|vivienda)-(?P<slug>[a-z0-9_-]+?)-i(?P<id>\d{10,16})\.htm"
_TYPE_WORDS = [
    ("atico", PropertyType.PENTHOUSE), ("ático", PropertyType.PENTHOUSE), ("duplex", PropertyType.DUPLEX),
    ("dúplex", PropertyType.DUPLEX), ("estudio", PropertyType.STUDIO), ("loft", PropertyType.STUDIO),
    ("casa", PropertyType.HOUSE), ("chalet", PropertyType.HOUSE), ("adosad", PropertyType.HOUSE),
    ("habitaci", PropertyType.ROOM), ("piso", PropertyType.FLAT), ("apartamento", PropertyType.FLAT),
]


class HabitacliaSource(Source):
    name = "habitaclia"
    pages = 2  # how many result pages to pull per search (15 listings each)

    def _urls(self, params: SearchParams) -> list[str]:
        city = params.city.lower().replace(" ", "_")
        base = "alquiler" if params.operation == Operation.RENT else "viviendas"
        urls = [f"https://www.habitaclia.com/{base}-{city}.htm"]
        urls += [f"https://www.habitaclia.com/{base}-{city}-{n}.htm" for n in range(2, self.pages + 1)]
        return urls

    async def search(self, params: SearchParams) -> list[Listing]:
        out: list[Listing] = []
        errors = []
        for url in self._urls(params):
            try:
                html = await fetch_html(url, self.name)
            except SourceError as exc:
                errors.append(str(exc))
                break
            cards = listing_cards(html, _HREF)
            for href, text in cards:
                try:
                    l = self._parse(href, text, params)
                    if l:
                        out.append(l)
                except Exception as exc:  # noqa: BLE001
                    log.debug("habitaclia: skip card: %s", exc)
        if not out:
            raise SourceError(errors[0] if errors else "habitaclia: no listings parsed (markup changed?)")
        return out

    def _parse(self, href: str, text: str, params: SearchParams) -> Listing | None:
        m = re.search(_HREF, href)
        pid, slug = m.group("id"), m.group("slug")
        price = euro(re.sub(r"[\d.,]+\s*€/m2", "", text))  # ignore the €/m² figure
        if not price:
            return None
        size = first_float(r"(\d+(?:[.,]\d+)?)\s*m2", text)
        beds = first_int(r"(\d+)\s*habitaci", text)
        baths = first_int(r"(\d+)\s*baño", text)
        loc = re.search(re.escape(params.city) + r"\s*-\s*([^\d€]+?)(?:\s+\d|$)", text, re.I)
        hood = loc.group(1).strip(" -") if loc else ""
        ptype = PropertyType.OTHER
        for w, t in _TYPE_WORDS:
            if w in slug or w in text.lower()[:80]:
                ptype = t
                break
        tm = re.match(r"(.{10,120}?)\s+" + re.escape(params.city), text, re.I)
        title = tm.group(1).strip() if tm else slug.replace("-", " ").capitalize()
        low = text.lower()
        return Listing(
            id=f"habitaclia:{pid}",
            source=self.name,
            url=href.split("?")[0] if href.startswith("http") else "https://www.habitaclia.com" + href.split("?")[0],
            operation=params.operation,
            property_type=ptype,
            title=title,
            description=text[:400],
            price=price,
            size_m2=size or 0.0,
            bedrooms=beds if beds is not None else (0 if ptype in (PropertyType.STUDIO, PropertyType.ROOM) else 1),
            bathrooms=baths or 1,
            city=params.city,
            neighborhood=hood,
            has_elevator=True if "ascensor" in low else None,
            has_terrace=True if "terraza" in low else None,
            has_parking=True if ("garaje" in low or "parking" in low) else None,
            furnished=True if "amueblad" in low else None,
        )
