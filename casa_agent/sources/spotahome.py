"""Spotahome scraper (rent only — mid/long-term furnished rentals).

Search page: https://www.spotahome.com/s/madrid--spain
Listing links look like /madrid/for-rent:apartments/1073266 (also :studios, :rooms).
Card text looks like:
  "Apartment From 21 Dec 3.5 (491) 2-bedroom apartment for rent in Embajadores, Madrid
   2600 €/month Size: 55m² Bathrooms: 1 BILLS INCLUDED ..."
No API key needed. Rooms in shared flats are returned as PropertyType.ROOM so the
user can filter them in or out.
"""
from __future__ import annotations

import logging
import re

from ..models import Listing, Operation, PropertyType, SearchParams
from ._scrape import euro, fetch_html, first_float, first_int, listing_cards
from .base import Source, SourceError

log = logging.getLogger(__name__)

_CITY_SLUG = {"madrid": "madrid--spain", "barcelona": "barcelona--spain", "valencia": "valencia--spain",
              "sevilla": "seville--spain", "malaga": "malaga--spain"}
_HREF = r"/(?P<city>[a-z-]+)/for-rent:(?P<kind>apartments|studios|rooms)/(?P<id>\d+)"


class SpotahomeSource(Source):
    name = "spotahome"

    async def search(self, params: SearchParams) -> list[Listing]:
        if params.operation != Operation.RENT:
            raise SourceError("spotahome: rentals only")
        slug = _CITY_SLUG.get(params.city.lower())
        if not slug:
            raise SourceError(f"spotahome: unknown city {params.city!r}")
        want_rooms = PropertyType.ROOM in params.property_types
        kinds = ["rooms"] if want_rooms else ["apartments", "studios"]
        url = f"https://www.spotahome.com/s/{slug}?" + "&".join(f"type[]={k}" for k in kinds)
        if params.max_price:
            url += f"&budget=0-{int(params.max_price)}"
        html = await fetch_html(url, self.name)
        cards = listing_cards(html, _HREF)
        if not cards:
            raise SourceError("spotahome: page loaded but no listing links found (markup changed?)")
        out = []
        for href, text in cards:
            try:
                l = self._parse(href, text, params)
                if l:
                    out.append(l)
            except Exception as exc:  # noqa: BLE001
                log.debug("spotahome: skip card: %s", exc)
        return out

    def _parse(self, href: str, text: str, params: SearchParams) -> Listing | None:
        m = re.search(_HREF, href)
        kind, pid = m.group("kind"), m.group("id")
        price = euro(text)
        if price is None:
            return None
        beds = first_int(r"(\d+)-bedroom", text)
        size = first_float(r"Size:\s*(\d+(?:[.,]\d+)?)\s*m", text) or 0.0
        baths = first_int(r"Bathrooms?:\s*(\d+)", text) or 1
        hood = ""
        hm = re.search(r"\bin\s+([^,]+?),\s*" + re.escape(params.city), text, re.I)
        if hm:
            hood = hm.group(1).strip()
        if kind == "rooms":
            ptype, beds = PropertyType.ROOM, 0
        elif kind == "studios":
            ptype, beds = PropertyType.STUDIO, 0
        else:
            ptype = PropertyType.FLAT
            beds = beds if beds is not None else 1
        tm = re.search(r"(\d+-bedroom .+?|Room in .+?|Studio .+?)(?:\s+\d+\s*€|$)", text)
        title = tm.group(1).strip() if tm else f"{ptype.value} in {hood or params.city}"
        avail = re.search(r"From (\d{1,2} \w{3}(?: \d{2})?)", text)
        return Listing(
            id=f"spotahome:{pid}",
            source=self.name,
            url=href if href.startswith("http") else "https://www.spotahome.com" + href,
            operation=Operation.RENT,
            property_type=ptype,
            title=title,
            description=("Available from " + avail.group(1) + ". " if avail else "") + ("Bills included. " if "BILLS INCLUDED" in text else ""),
            price=price,
            size_m2=size,
            bedrooms=beds,
            bathrooms=baths,
            city=params.city,
            neighborhood=hood,
            furnished=True,  # Spotahome listings are furnished
        )
