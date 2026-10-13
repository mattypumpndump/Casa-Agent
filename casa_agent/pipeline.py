"""Normalise → dedup → filter → enrich → score.

Pure functions over Listing objects; no network, no LLM. Easy to unit-test.
"""
from __future__ import annotations

import asyncio
import logging
import math
import re
import unicodedata
from collections import defaultdict
from datetime import date
from statistics import median

from . import config
from .models import Listing, Operation, PropertyType, ScoredListing, SearchParams, SearchResult
from .sources import Source, SourceError

log = logging.getLogger(__name__)


# ---------------------------------------------------------------- fetching


async def fetch_all(sources: list[Source], params: SearchParams) -> tuple[list[Listing], dict[str, str]]:
    """Query every source concurrently. Returns (listings, {source: error})."""

    async def one(src: Source):
        try:
            return src.name, await src.search(params), None
        except SourceError as exc:
            return src.name, [], str(exc)
        except Exception as exc:  # noqa: BLE001 - never let one source kill the run
            log.exception("Source %s crashed", src.name)
            return src.name, [], f"{type(exc).__name__}: {exc}"

    results = await asyncio.gather(*(one(s) for s in sources))
    listings: list[Listing] = []
    failed: dict[str, str] = {}
    for name, ls, err in results:
        if err:
            failed[name] = err
            log.warning("Source %s failed: %s", name, err)
        listings.extend(ls)
    return listings, failed


# ---------------------------------------------------------------- dedup


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode()
    s = re.sub(r"[^a-z0-9 ]", " ", s.lower())
    s = re.sub(r"\b(calle|c|av|avenida|paseo|pza|plaza|de|del|la|el|los|las)\b", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _same_property(a: Listing, b: Listing) -> bool:
    """Heuristic match across portals: same core facts + same place."""
    if a.bedrooms != b.bedrooms or a.bathrooms != b.bathrooms:
        return False
    if abs(a.size_m2 - b.size_m2) > max(3, 0.04 * a.size_m2):
        return False
    if a.price and b.price and abs(a.price - b.price) / max(a.price, b.price) > 0.08:
        return False
    if a.floor is not None and b.floor is not None and a.floor != b.floor:
        return False
    # Location evidence: coordinates, or address, or at least neighbourhood
    if a.lat and a.lon and b.lat and b.lon:
        if _haversine_m(a.lat, a.lon, b.lat, b.lon) > 150:
            return False
        return True
    if a.address and b.address:
        return _norm(a.address) == _norm(b.address)
    return bool(a.neighborhood) and _norm(a.neighborhood) == _norm(b.neighborhood)


def _haversine_m(lat1, lon1, lat2, lon2) -> float:
    r = 6371000
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def dedup(listings: list[Listing]) -> list[Listing]:
    """Merge the same property seen on several portals.

    Keeps the cheapest copy (that's the one you'd actually use) and records
    the other sources in `also_on`. Fills gaps (photos, description, flags)
    from the duplicates.
    """
    # Bucket by (beds, baths, rounded size) so we don't do O(n²) across everything
    buckets: dict[tuple, list[Listing]] = defaultdict(list)
    for l in listings:
        buckets[(l.bedrooms, l.bathrooms, round(l.size_m2 / 5))].append(l)
        buckets[(l.bedrooms, l.bathrooms, round(l.size_m2 / 5) + 1)].append(l)

    seen: set[str] = set()
    merged: list[Listing] = []
    for l in listings:
        if l.id in seen:
            continue
        group = [l]
        for key in ((l.bedrooms, l.bathrooms, round(l.size_m2 / 5)), (l.bedrooms, l.bathrooms, round(l.size_m2 / 5) + 1)):
            for other in buckets.get(key, []):
                if other.id != l.id and other.id not in seen and other.source != l.source and _same_property(l, other):
                    if other not in group:
                        group.append(other)
        for g in group:
            seen.add(g.id)
        best = min(group, key=lambda x: x.price)
        if len(group) > 1:
            best = best.model_copy()
            best.also_on = sorted({g.source for g in group if g.source != best.source})
            for g in group:
                if not best.photos and g.photos:
                    best.photos = g.photos
                if len(g.description) > len(best.description):
                    best.description = g.description
                for f in ("has_elevator", "has_terrace", "has_parking", "has_air_conditioning",
                          "exterior", "furnished", "pets_allowed", "year_built", "energy_rating", "published"):
                    if getattr(best, f) is None and getattr(g, f) is not None:
                        setattr(best, f, getattr(g, f))
        merged.append(best)
    return merged


# ---------------------------------------------------------------- filtering


def hard_filter(listings: list[Listing], p: SearchParams) -> list[Listing]:
    def ok(l: Listing) -> bool:
        if l.price <= 0:
            return False
        if l.size_m2 <= 0 and l.property_type != PropertyType.ROOM:
            return False
        if p.max_price and l.price > p.max_price:
            return False
        if p.min_price and l.price < p.min_price:
            return False
        if p.min_size_m2 and l.size_m2 < p.min_size_m2:
            return False
        if p.min_bedrooms is not None and l.bedrooms < p.min_bedrooms:
            return False
        if p.min_bathrooms and l.bathrooms < p.min_bathrooms:
            return False
        if p.property_types and l.property_type not in p.property_types:
            return False
        if p.districts and not any(_norm(d) in _norm(l.district) or _norm(d) in _norm(l.neighborhood) for d in p.districts):
            return False
        if p.needs_elevator and l.has_elevator is False:
            return False
        if p.needs_terrace and l.has_terrace is False:
            return False
        if p.needs_parking and l.has_parking is False:
            return False
        if p.needs_furnished and l.furnished is False:
            return False
        if p.needs_pets and l.pets_allowed is False:
            return False
        if p.needs_air_conditioning and l.has_air_conditioning is False:
            return False
        return True

    return [l for l in listings if ok(l)]


# ---------------------------------------------------------------- enrichment


def enrich(listings: list[Listing], universe: list[Listing]) -> list[Listing]:
    """Add €/m², zone benchmark, days on market.

    `universe` is the full deduped set (before user filters) so zone averages
    reflect the market, not just what the user can afford.
    """
    by_zone: dict[str, list[float]] = defaultdict(list)
    for l in universe:
        if l.size_m2 > 0 and l.price > 0:
            by_zone[_norm(l.district) or _norm(l.neighborhood) or _norm(l.city)].append(l.price / l.size_m2)
    zone_med = {z: median(v) for z, v in by_zone.items() if len(v) >= 3}
    overall = median([x for v in by_zone.values() for x in v]) if by_zone else None

    today = date.today()
    out = []
    for l in listings:
        l = l.model_copy()
        l.price_per_m2 = round(l.price / l.size_m2, 2) if l.size_m2 > 0 else None
        ref = zone_med.get(_norm(l.district) or _norm(l.neighborhood) or _norm(l.city), overall)
        if ref and l.price_per_m2:
            l.zone_avg_price_per_m2 = round(ref, 2)
            l.price_vs_zone_pct = round((l.price_per_m2 - ref) / ref * 100, 1)
        if l.published:
            l.days_on_market = (today - l.published).days
        out.append(l)
    return out


# ---------------------------------------------------------------- scoring


def _clamp(x: float, lo=0.0, hi=1.0) -> float:
    return max(lo, min(hi, x))


def score(l: Listing, p: SearchParams) -> ScoredListing:
    pros, cons, flags = [], [], []
    b: dict[str, float] = {}

    # --- price (relative to budget and to zone)
    if p.max_price:
        budget_use = l.price / p.max_price
        s_budget = _clamp(1.4 - budget_use)  # 60% of budget → 0.8, 100% → 0.4
    else:
        s_budget = 0.6
    s_zone = 0.5
    if l.price_vs_zone_pct is not None:
        s_zone = _clamp(0.5 - l.price_vs_zone_pct / 40)  # -20% → 1.0, +20% → 0
        if l.price_vs_zone_pct <= -10:
            pros.append(f"{abs(l.price_vs_zone_pct):.0f}% below the {l.district or 'zone'} average €/m²")
        elif l.price_vs_zone_pct >= 15:
            cons.append(f"{l.price_vs_zone_pct:.0f}% above the {l.district or 'zone'} average €/m²")
            if l.price_vs_zone_pct >= 30:
                flags.append("Priced well above comparable listings — negotiate or verify what justifies it")
    b["price"] = 0.5 * s_budget + 0.5 * s_zone

    # --- size & household fit
    people = max(1, p.household_size)
    m2_pp = l.size_m2 / people
    s_size = _clamp((m2_pp - 12) / 25)  # 12 m²/person → 0, 37 → 1
    rooms_needed = max(1, math.ceil(people / 2)) if people > 1 else 0
    if l.bedrooms < rooms_needed:
        cons.append(f"Only {l.bedrooms} bedroom(s) for {people} people")
        s_size *= 0.6
    elif l.bedrooms >= rooms_needed + 1 and people > 1:
        pros.append("Spare room for office/guests")
    if m2_pp < 18 and people > 1:
        flags.append(f"Tight: ~{m2_pp:.0f} m² per person")
    if p.min_size_m2 and l.size_m2 >= p.min_size_m2 * 1.25:
        pros.append(f"Roomy: {l.size_m2:.0f} m²")
    b["size"] = s_size

    # --- location
    s_loc = 0.5
    if p.districts:
        s_loc = 1.0 if any(_norm(d) == _norm(l.district) for d in p.districts) else 0.8
        pros.append(f"In requested zone: {l.district}")
    if l.exterior:
        s_loc += 0.1
    elif l.exterior is False:
        cons.append("Interior-facing")
        s_loc -= 0.1
    b["location"] = _clamp(s_loc)

    # --- amenities
    am = 0.0
    wants = {
        "elevator": (p.needs_elevator, l.has_elevator, "Elevator"),
        "terrace": (p.needs_terrace, l.has_terrace, "Terrace"),
        "parking": (p.needs_parking, l.has_parking, "Parking"),
        "ac": (p.needs_air_conditioning, l.has_air_conditioning, "Air conditioning"),
        "furnished": (p.needs_furnished, l.furnished, "Furnished"),
        "pets": (p.needs_pets, l.pets_allowed, "Pets allowed"),
    }
    n = 0
    for _, (wanted, has, label) in wants.items():
        weight = 2 if wanted else 1
        n += weight
        if has:
            am += weight
            if wanted or label in ("Terrace", "Parking"):
                pros.append(label)
        elif wanted and has is None:
            flags.append(f"{label} requested but not stated in the listing — confirm")
            am += weight * 0.4
    if l.has_elevator is False and (l.floor or 0) >= 3:
        cons.append(f"{l.floor}th floor without elevator")
    b["amenities"] = _clamp(am / n if n else 0.5)

    # --- info quality / red flags (small penalty, mostly flags)
    if l.days_on_market is not None and l.days_on_market > 90:
        flags.append(f"On the market {l.days_on_market} days — ask why")
    if l.energy_rating in ("F", "G"):
        cons.append(f"Energy rating {l.energy_rating} (higher bills)")
    if l.year_built and l.year_built < 1960 and not re.search(r"reform", (l.title + l.description).lower()):
        flags.append(f"Built {l.year_built}, no mention of renovation")
    if l.also_on:
        pros.append("Listed on " + ", ".join([l.source] + l.also_on) + " (cheapest copy shown)")
    if l.operation == Operation.BUY and l.monthly_community_fees:
        if l.monthly_community_fees > 150:
            cons.append(f"Community fees €{l.monthly_community_fees:.0f}/month")

    total = (
        p.weight_price * b["price"]
        + p.weight_size * b["size"]
        + p.weight_location * b["location"]
        + p.weight_amenities * b["amenities"]
    ) / max(1e-9, p.weight_price + p.weight_size + p.weight_location + p.weight_amenities)
    total -= 0.02 * len(flags)

    return ScoredListing(
        listing=l,
        score=round(_clamp(total) * 100, 1),
        score_breakdown={k: round(v * 100) for k, v in b.items()},
        pros=pros[:5],
        cons=cons[:5],
        flags=flags[:4],
    )


# ---------------------------------------------------------------- orchestration


async def run_search(params: SearchParams, sources: list[Source], top_n: int | None = None) -> SearchResult:
    top_n = top_n or config.TOP_N
    raw, failed = await fetch_all(sources, params)
    # Demo data is a fallback: if any real source returned listings, drop the synthetic ones
    real = [l for l in raw if not l.source.startswith("demo")]
    if real:
        raw = real
    universe = dedup(raw)
    matching = hard_filter(universe, params)
    matching = enrich(matching, universe)
    scored = sorted((score(l, params) for l in matching), key=lambda s: s.score, reverse=True)
    return SearchResult(
        params=params,
        sources_queried=[s.name for s in sources],
        sources_failed=failed,
        total_found=len(raw),
        after_dedup=len(universe),
        matching=len(matching),
        options=scored[:top_n],
    )
