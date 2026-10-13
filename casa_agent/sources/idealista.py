"""Idealista official API client.

Register at https://developers.idealista.com/ to get an API key + secret
(free tier: ~100 requests/month at time of writing). Set IDEALISTA_API_KEY
and IDEALISTA_SECRET in .env and add "idealista" to CASA_SOURCES.
"""
from __future__ import annotations

import base64
import logging
from datetime import date, timedelta

import httpx

from .. import config
from ..models import Listing, Operation, PropertyType, SearchParams
from .base import Source, SourceError

log = logging.getLogger(__name__)

TOKEN_URL = "https://api.idealista.com/oauth/token"
SEARCH_URL = "https://api.idealista.com/3.5/es/search"

# Approximate city centres for the API's center+distance search
CITY_CENTERS = {
    "madrid": (40.4168, -3.7038),
    "barcelona": (41.3874, 2.1686),
    "valencia": (39.4699, -0.3763),
    "sevilla": (37.3891, -5.9845),
    "malaga": (36.7213, -4.4214),
}

_TYPE_MAP = {
    "flat": PropertyType.FLAT,
    "penthouse": PropertyType.PENTHOUSE,
    "duplex": PropertyType.DUPLEX,
    "studio": PropertyType.STUDIO,
    "chalet": PropertyType.HOUSE,
    "countryHouse": PropertyType.HOUSE,
}


class IdealistaSource(Source):
    name = "idealista"

    def __init__(self) -> None:
        self._token: str | None = None

    async def _get_token(self, client: httpx.AsyncClient) -> str:
        if self._token:
            return self._token
        if not (config.IDEALISTA_API_KEY and config.IDEALISTA_SECRET):
            raise SourceError("IDEALISTA_API_KEY / IDEALISTA_SECRET not set")
        creds = base64.b64encode(
            f"{config.IDEALISTA_API_KEY}:{config.IDEALISTA_SECRET}".encode()
        ).decode()
        r = await client.post(
            TOKEN_URL,
            headers={"Authorization": f"Basic {creds}"},
            data={"grant_type": "client_credentials", "scope": "read"},
        )
        if r.status_code != 200:
            raise SourceError(f"Idealista auth failed: {r.status_code} {r.text[:200]}")
        self._token = r.json()["access_token"]
        return self._token

    async def search(self, params: SearchParams) -> list[Listing]:
        center = CITY_CENTERS.get(params.city.lower())
        if not center:
            raise SourceError(f"No coordinates known for city {params.city!r}")

        body: dict = {
            "country": "es",
            "operation": "rent" if params.operation == Operation.RENT else "sale",
            "propertyType": "homes",
            "center": f"{center[0]},{center[1]}",
            "distance": 12000,
            "maxItems": 50,
            "numPage": 1,
            "order": "price",
            "sort": "asc",
        }
        if params.max_price:
            body["maxPrice"] = params.max_price
        if params.min_price:
            body["minPrice"] = params.min_price
        if params.min_size_m2:
            body["minSize"] = params.min_size_m2
        if params.min_bedrooms:
            body["bedrooms"] = ",".join(str(b) for b in range(params.min_bedrooms, 5))
        if params.needs_elevator:
            body["elevator"] = True
        if params.needs_terrace:
            body["terrace"] = True
        if params.needs_parking:
            body["garage"] = True
        if params.needs_furnished and params.operation == Operation.RENT:
            body["furnished"] = "furnished"

        async with httpx.AsyncClient(timeout=config.SCRAPE_TIMEOUT) as client:
            token = await self._get_token(client)
            r = await client.post(
                SEARCH_URL,
                headers={"Authorization": f"Bearer {token}"},
                data=body,
            )
            if r.status_code != 200:
                raise SourceError(f"Idealista search failed: {r.status_code} {r.text[:200]}")
            data = r.json()

        return [self._to_listing(e, params) for e in data.get("elementList", [])]

    def _to_listing(self, e: dict, params: SearchParams) -> Listing:
        return Listing(
            id=f"idealista:{e['propertyCode']}",
            source=self.name,
            url=e.get("url", f"https://www.idealista.com/inmueble/{e['propertyCode']}/"),
            operation=params.operation,
            property_type=_TYPE_MAP.get(e.get("propertyType", ""), PropertyType.OTHER),
            title=e.get("suggestedTexts", {}).get("title", ""),
            description=e.get("description", "") or "",
            price=float(e["price"]),
            size_m2=float(e.get("size", 0) or 0),
            bedrooms=int(e.get("rooms", 0) or 0),
            bathrooms=int(e.get("bathrooms", 0) or 0),
            floor=_parse_floor(e.get("floor")),
            city=e.get("municipality", params.city),
            district=e.get("district", "") or "",
            neighborhood=e.get("neighborhood", "") or "",
            address=e.get("address", "") or "",
            lat=e.get("latitude"),
            lon=e.get("longitude"),
            has_elevator=e.get("hasLift"),
            has_terrace=e.get("hasTerrace"),
            has_parking=bool(e.get("parkingSpace", {}).get("hasParkingSpace")) if e.get("parkingSpace") else None,
            has_air_conditioning=e.get("hasAirConditioning"),
            exterior=e.get("exterior"),
            furnished=e.get("furnished"),
            year_built=e.get("constructionYear"),
            energy_rating=e.get("energyCertification", {}).get("rating") if isinstance(e.get("energyCertification"), dict) else None,
            photos=[p.get("url") for p in e.get("multimedia", {}).get("images", []) if p.get("url")][:6] or ([e["thumbnail"]] if e.get("thumbnail") else []),
            published=_estimate_published(e),
        )


def _parse_floor(v) -> int | None:
    if v in (None, "", "bj", "en", "st", "ss"):
        return 0 if v in ("bj", "en", "st") else None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _estimate_published(e: dict) -> date | None:
    # The search endpoint doesn't expose a publish date directly; some
    # responses include "newDevelopment"/"hasVideo" etc. Keep None unless present.
    if "publishDate" in e:
        try:
            return date.fromisoformat(e["publishDate"][:10])
        except ValueError:
            return None
    return None
