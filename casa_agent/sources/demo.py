"""Offline demo source.

Generates realistic-looking Madrid listings so the whole pipeline (dedup,
scoring, survey, web UI) can be developed and demoed without API keys or
hitting real portals. Deterministic: same seed → same listings.

It simulates TWO portals ("demo-idealista" and "demo-fotocasa") and makes
~30% of properties appear on both, sometimes at slightly different prices,
so the dedup step has something real to do.
"""
from __future__ import annotations

import random
from datetime import date, timedelta

from ..models import Listing, Operation, PropertyType, SearchParams
from .base import Source

# district -> (neighbourhoods, rent €/m²/month, sale €/m²)
MADRID_ZONES = {
    "Centro": (["Malasaña", "Chueca", "Lavapiés", "Sol", "Palacio"], 24, 6200),
    "Salamanca": (["Goya", "Recoletos", "Lista", "Castellana"], 27, 8500),
    "Chamberí": (["Trafalgar", "Almagro", "Arapiles", "Gaztambide"], 25, 7300),
    "Retiro": (["Ibiza", "Niño Jesús", "Pacífico", "Jerónimos"], 22, 6300),
    "Chamartín": (["Hispanoamérica", "Nueva España", "Prosperidad", "El Viso"], 23, 6900),
    "Tetuán": (["Cuatro Caminos", "Bellas Vistas", "Valdeacederas", "Berruguete"], 19, 4600),
    "Arganzuela": (["Delicias", "Legazpi", "Imperial", "Acacias"], 20, 5000),
    "Moncloa-Aravaca": (["Argüelles", "Aravaca", "Ciudad Universitaria", "Valdezarza"], 21, 5500),
    "Carabanchel": (["Vista Alegre", "Opañel", "San Isidro", "Puerta Bonita"], 15, 3100),
    "Latina": (["Aluche", "Lucero", "Puerta del Ángel", "Las Águilas"], 15, 3000),
    "Usera": (["Moscardó", "Orcasitas", "Almendrales"], 14, 2800),
    "Puente de Vallecas": (["Numancia", "Portazgo", "San Diego"], 14, 2600),
    "Hortaleza": (["Canillas", "Pinar del Rey", "Sanchinarro"], 18, 4300),
    "Ciudad Lineal": (["Pueblo Nuevo", "Quintana", "Concepción", "Ventas"], 17, 3900),
    "Fuencarral-El Pardo": (["Las Tablas", "Mirasierra", "Peñagrande"], 18, 4400),
    "Villaverde": (["Villaverde Alto", "San Cristóbal", "Butarque"], 12, 2300),
}

_ADJ = ["Luminoso", "Reformado", "Amplio", "Acogedor", "Exterior", "Espectacular", "Céntrico", "Tranquilo"]
_STREETS = ["Calle de Alcalá", "Calle Mayor", "Paseo de la Castellana", "Calle de Bravo Murillo",
            "Calle de Embajadores", "Calle de Toledo", "Calle de Fuencarral", "Calle de Serrano",
            "Calle del General Ricardos", "Avenida de la Albufera", "Calle de Arturo Soria", "Calle de López de Hoyos"]


_IDEALISTA_SLUG = {
    "Centro": "centro", "Salamanca": "salamanca", "Chamberí": "chamberi", "Retiro": "retiro",
    "Chamartín": "chamartin", "Tetuán": "tetuan", "Arganzuela": "arganzuela", "Moncloa-Aravaca": "moncloa",
    "Carabanchel": "carabanchel", "Latina": "latina", "Usera": "usera", "Puente de Vallecas": "puente-de-vallecas",
    "Hortaleza": "hortaleza", "Ciudad Lineal": "ciudad-lineal", "Fuencarral-El Pardo": "fuencarral", "Villaverde": "villaverde",
}


def _real_search_url(portal: str, district: str, operation: Operation, beds: int) -> str:
    """Demo listings are synthetic, so link to the portal's real search for the same zone."""
    slug = _IDEALISTA_SLUG.get(district, district.lower())
    if portal == "idealista":
        op = "alquiler-viviendas" if operation == Operation.RENT else "venta-viviendas"
        url = f"https://www.idealista.com/{op}/madrid/{slug}/"
        return url + (f"con-de-{min(beds, 4)}-dormitorios/" if beds else "")
    op = "alquiler" if operation == Operation.RENT else "comprar"
    return f"https://www.fotocasa.es/es/{op}/viviendas/madrid-capital/{slug}/l"


class DemoSource(Source):
    name = "demo"

    def __init__(self, seed: int = 42, n_properties: int = 400) -> None:
        self.seed = seed
        self.n = n_properties

    async def search(self, params: SearchParams) -> list[Listing]:
        from .. import fs
        zone_data = fs.zones("Madrid")
        zones = {d: (z["neighborhoods"], z["rent_eur_m2_month"], z["sale_eur_m2"]) for d, z in zone_data.items()} or MADRID_ZONES
        rng = random.Random(f"{self.seed}-{params.operation.value}")
        out: list[Listing] = []
        today = date.today()
        for i in range(self.n):
            district = rng.choice(list(zones))
            hoods, rent_m2, sale_m2 = zones[district]
            hood = rng.choice(hoods)
            ptype = rng.choices(
                [PropertyType.FLAT, PropertyType.STUDIO, PropertyType.PENTHOUSE, PropertyType.DUPLEX, PropertyType.HOUSE],
                weights=[70, 10, 8, 7, 5],
            )[0]
            if ptype == PropertyType.STUDIO:
                size, beds, baths = rng.randint(25, 45), 0, 1
            elif ptype == PropertyType.HOUSE:
                size, beds, baths = rng.randint(140, 320), rng.randint(3, 5), rng.randint(2, 4)
            else:
                beds = rng.choices([1, 2, 3, 4], weights=[25, 40, 28, 7])[0]
                size = int(rng.gauss(35 + beds * 22, 10))
                size = max(30, size)
                baths = 1 if beds <= 2 else rng.randint(1, 2)
            base_m2 = rent_m2 if params.operation == Operation.RENT else sale_m2
            noise = rng.gauss(1.0, 0.18)
            # Older/no-lift flats cheaper, penthouses/terraces pricier
            floor = rng.randint(0, 8) if ptype != PropertyType.HOUSE else None
            elevator = rng.random() < (0.85 if floor and floor > 2 else 0.6)
            terrace = ptype == PropertyType.PENTHOUSE or rng.random() < 0.25
            if not elevator:
                noise *= 0.9
            if terrace:
                noise *= 1.08
            price = size * base_m2 * noise
            price = round(price / (10 if params.operation == Operation.RENT else 1000)) * (10 if params.operation == Operation.RENT else 1000)
            year = rng.choice([1920, 1950, 1965, 1975, 1985, 1995, 2005, 2015, 2021])
            published = today - timedelta(days=int(rng.expovariate(1 / 25)))
            street = rng.choice(_STREETS)
            num = rng.randint(1, 180)
            exterior = rng.random() < 0.7
            adj = rng.choice([a for a in _ADJ if a != "Exterior" or exterior])
            common = dict(
                operation=params.operation,
                property_type=ptype,
                title=f"{adj} {ptype.value} en {hood}, {district}",
                description=(
                    "[DEMO LISTING — synthetic data; the link opens the portal's real search for this zone] "
                    f"{ptype.value.capitalize()} de {size} m² con {beds} dormitorios y {baths} baños en {hood}. "
                    f"Edificio de {year}{', con ascensor' if elevator else ', sin ascensor'}"
                    f"{', terraza' if terrace else ''}. Cerca de transporte público."
                ),
                size_m2=float(size),
                bedrooms=beds,
                bathrooms=baths,
                floor=floor,
                city="Madrid",
                district=district,
                neighborhood=hood,
                address=f"{street}, {num}",
                lat=round(40.42 + rng.uniform(-0.08, 0.08), 5),
                lon=round(-3.70 + rng.uniform(-0.1, 0.1), 5),
                has_elevator=elevator,
                has_terrace=terrace,
                has_parking=rng.random() < 0.2,
                has_air_conditioning=rng.random() < 0.55,
                exterior=exterior,
                furnished=(rng.random() < 0.6) if params.operation == Operation.RENT else False,
                pets_allowed=(rng.random() < 0.35) if params.operation == Operation.RENT else None,
                year_built=year,
                energy_rating=rng.choice(list("ABCDEEEFG")),
                monthly_community_fees=round(rng.uniform(40, 180)) if params.operation == Operation.BUY else None,
                photos=[],
                published=published,
            )
            out.append(Listing(id=f"demo-idealista:{10000 + i}", source="demo-idealista",
                               url=_real_search_url("idealista", district, params.operation, beds), price=float(price), **common))
            if rng.random() < 0.3:  # same property on second portal, maybe different price
                p2 = price * rng.choice([1.0, 1.0, 1.03, 0.97])
                p2 = round(p2 / 10) * 10 if params.operation == Operation.RENT else round(p2 / 1000) * 1000
                dup = dict(common)
                dup["published"] = published + timedelta(days=rng.randint(-3, 3))
                dup["title"] = f"{ptype.value.capitalize()} en {street}, {hood}"
                out.append(Listing(id=f"demo-fotocasa:{50000 + i}", source="demo-fotocasa",
                                   url=_real_search_url("fotocasa", district, params.operation, beds), price=float(p2), **dup))
        return out
