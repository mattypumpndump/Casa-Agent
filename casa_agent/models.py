"""Common schema shared by every source, the pipeline and the web app.

Every scraper/API client MUST return `Listing` objects. The rest of the
system never looks at raw site data, so adding a new portal only means
writing one adapter that produces Listings.
"""
from __future__ import annotations

from datetime import date
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class Operation(str, Enum):
    RENT = "rent"
    BUY = "buy"


class PropertyType(str, Enum):
    FLAT = "flat"
    HOUSE = "house"
    STUDIO = "studio"
    PENTHOUSE = "penthouse"
    DUPLEX = "duplex"
    ROOM = "room"
    OTHER = "other"


class Listing(BaseModel):
    """One property as advertised on one portal."""

    id: str = Field(description="Unique within the source, e.g. 'idealista:12345'")
    source: str
    url: str
    operation: Operation
    property_type: PropertyType = PropertyType.FLAT

    title: str = ""
    description: str = ""

    price: float = Field(description="EUR. Monthly for rent, total for buy.")
    size_m2: float
    bedrooms: int
    bathrooms: int
    floor: Optional[int] = None

    # Location
    city: str = "Madrid"
    district: str = ""
    neighborhood: str = ""
    address: str = ""
    lat: Optional[float] = None
    lon: Optional[float] = None

    # Attributes
    has_elevator: Optional[bool] = None
    has_terrace: Optional[bool] = None
    has_parking: Optional[bool] = None
    has_air_conditioning: Optional[bool] = None
    exterior: Optional[bool] = None
    furnished: Optional[bool] = None
    pets_allowed: Optional[bool] = None
    year_built: Optional[int] = None
    energy_rating: Optional[str] = None
    monthly_community_fees: Optional[float] = None

    photos: list[str] = Field(default_factory=list)
    published: Optional[date] = None

    # Filled by the enrichment step
    price_per_m2: Optional[float] = None
    zone_avg_price_per_m2: Optional[float] = None
    price_vs_zone_pct: Optional[float] = Field(
        default=None, description="+10 means 10% above the zone average"
    )
    days_on_market: Optional[int] = None
    also_on: list[str] = Field(
        default_factory=list, description="Other sources where the same property was found"
    )

    def key_facts(self) -> str:
        return (
            f"{self.bedrooms}bd/{self.bathrooms}ba, {self.size_m2:.0f} m², "
            f"{self.district or self.city}, €{self.price:,.0f}"
        )


class SearchParams(BaseModel):
    """What the user wants. Produced by the intake agent from free text."""

    operation: Operation = Operation.RENT
    city: str = "Madrid"
    districts: list[str] = Field(default_factory=list, description="Preferred districts/zones; empty = anywhere")

    max_price: Optional[float] = None
    min_price: Optional[float] = None
    min_size_m2: Optional[float] = None
    min_bedrooms: Optional[int] = None
    min_bathrooms: Optional[int] = None

    household_size: int = Field(default=1, description="People who will live there")
    property_types: list[PropertyType] = Field(default_factory=list)

    needs_elevator: bool = False
    needs_terrace: bool = False
    needs_parking: bool = False
    needs_furnished: bool = False
    needs_pets: bool = False
    needs_air_conditioning: bool = False

    # 0-1 weights for scoring; the agent sets these from what the user emphasises
    weight_price: float = 0.35
    weight_size: float = 0.2
    weight_location: float = 0.25
    weight_amenities: float = 0.2

    notes: str = Field(default="", description="Free-text preferences not captured above")

    def summary(self) -> str:
        parts = [f"{self.operation.value} in {self.city}"]
        if self.districts:
            parts.append("zones: " + ", ".join(self.districts))
        if self.max_price:
            parts.append(f"max €{self.max_price:,.0f}")
        if self.min_bedrooms:
            parts.append(f"≥{self.min_bedrooms} bedrooms")
        if self.min_size_m2:
            parts.append(f"≥{self.min_size_m2:.0f} m²")
        parts.append(f"{self.household_size} people")
        return "; ".join(parts)


class ScoredListing(BaseModel):
    listing: Listing
    score: float = Field(description="0-100")
    score_breakdown: dict[str, float] = Field(default_factory=dict)
    pros: list[str] = Field(default_factory=list)
    cons: list[str] = Field(default_factory=list)
    flags: list[str] = Field(default_factory=list, description="Red flags worth checking")


class SearchResult(BaseModel):
    params: SearchParams
    sources_queried: list[str]
    sources_failed: dict[str, str] = Field(default_factory=dict)
    total_found: int
    after_dedup: int
    matching: int
    options: list[ScoredListing]
    survey: str = Field(default="", description="Markdown report written by the analyst agent")
