"""Parser tests on HTML fixtures shaped like the live pages (Oct 2026)."""
from casa_agent.models import Operation, PropertyType, SearchParams
from casa_agent.sources._scrape import euro, listing_cards
from casa_agent.sources.habitaclia import HabitacliaSource, _HREF as HAB_HREF
from casa_agent.sources.pisos import PisosSource, _HREF as PISOS_HREF
from casa_agent.sources.spotahome import SpotahomeSource, _HREF as SPOT_HREF

SPOT_HTML = """
<div class="list"><div class="x"><a href="/madrid/for-rent:apartments/1073266">1/28</a>
 <div><span>Apartment</span><span>From 21 Dec</span><span>3.5 (491)</span>
 <a href="https://www.spotahome.com/madrid/for-rent:apartments/1073266">2-bedroom apartment for rent in Embajadores, Madrid</a>
 <p>2600 €/month</p><span>INSTANT BOOKING</span>
 <ul><li><b>Size:</b> 55m²</li><li><b>Bathrooms:</b> 1</li></ul></div></div>
<div class="x"><a href="/madrid/for-rent:rooms/1482111">Room in 5-bedroom flat in Almendrales, Madrid</a>
 <p>670 €/month</p><span>BILLS INCLUDED</span></div>
<div class="x"><a href="/madrid/for-rent:apartments/823168">3-bedroom apartment for rent in Madrid, Madrid</a>
 <p>1500 €/month</p><b>Size:</b> 70m² <b>Bathrooms:</b> 2 BILLS INCLUDED</div></div>
"""

HAB_HTML = """
<article><h3><a href="https://www.habitaclia.com/alquiler-piso-embajadores_lavapies-madrid-i16831000022808.htm?f=&geo=p">Piso en alquiler en Embajadores-Lavapiés, Madrid</a></h3>
<p>Madrid - Embajadores-Lavapiés</p><p>106m2 - 3 habitaciones - 2 baños - 26,89€/m2</p>
<p>Piso exterior con ascensor y terraza.</p><span>2.850 €</span></article>
<article><h3><a href="https://www.habitaclia.com/alquiler-atico-lista-madrid-i15455000003638.htm">Ático en alquiler en Lista</a></h3>
<p>Madrid - Lista</p><p>198m2 - 3 habitaciones - 3 baños - 24,24€/m2</p><span>4.800 €</span></article>
<article><h3><a href="https://www.habitaclia.com/alquiler-piso-palos-madrid-i50198000004502.htm">Piso en Palos de Moguer</a></h3>
<p>Madrid - Palos de Moguer</p><p>50m2 - 2 habitaciones - 1 baño - 34,00€/m2</p><span>1.700 €</span><em>Ha bajado 100 €</em></article>
"""

PISOS_HTML = """
<div class="ad"><a href="/alquilar/piso-madrid_capital_centro_sol-51234567/">Piso en Calle Mayor, Sol</a>
<span>3 habs.</span><span>2 baños</span><span>95 m²</span><span>Con ascensor y garaje</span><span>2.300 €/mes</span></div>
<div class="ad"><a href="https://www.pisos.com/comprar/atico-madrid_capital_retiro_ibiza-51234568/">Ático en Ibiza</a>
<span>2 habs.</span><span>1 baño</span><span>80 m²</span><span>650.000 €</span></div>
"""


def test_euro():
    assert euro("2.850 €") == 2850
    assert euro("2600 €/month") == 2600
    assert euro("650.000 €") == 650000
    assert euro("1.234,50 €") == 1234.5
    assert euro("no price") is None


def test_listing_cards_dedups_links():
    cards = listing_cards(SPOT_HTML, SPOT_HREF)
    assert [c[0].split("/")[-1] for c in cards] == ["1073266", "1482111", "823168"]


def test_spotahome_parse():
    src = SpotahomeSource()
    p = SearchParams(city="Madrid")
    ls = [src._parse(h, t, p) for h, t in listing_cards(SPOT_HTML, SPOT_HREF)]
    a, room, b = ls
    assert a.price == 2600 and a.size_m2 == 55 and a.bedrooms == 2 and a.bathrooms == 1
    assert a.neighborhood == "Embajadores" and a.url.endswith("/1073266")
    assert a.title.startswith("2-bedroom apartment")
    assert room.property_type == PropertyType.ROOM and room.price == 670 and "Bills included" in room.description
    assert b.bedrooms == 3 and b.bathrooms == 2 and b.size_m2 == 70


def test_habitaclia_parse():
    src = HabitacliaSource()
    p = SearchParams(city="Madrid", operation=Operation.RENT)
    ls = [src._parse(h, t, p) for h, t in listing_cards(HAB_HTML, HAB_HREF)]
    a, b, c = ls
    assert a.price == 2850 and a.size_m2 == 106 and a.bedrooms == 3 and a.bathrooms == 2
    assert a.neighborhood == "Embajadores-Lavapiés" and a.url.endswith("i16831000022808.htm")
    assert a.has_elevator and a.has_terrace
    assert b.property_type == PropertyType.PENTHOUSE and b.price == 4800
    assert c.price == 1700 and c.bathrooms == 1  # ignores the "100 €" drop note and €/m²


def test_pisos_parse():
    src = PisosSource()
    ls = [src._parse(h, t, SearchParams(city="Madrid")) for h, t in listing_cards(PISOS_HTML, PISOS_HREF)]
    a, b = ls
    assert a.price == 2300 and a.bedrooms == 3 and a.bathrooms == 2 and a.size_m2 == 95
    assert a.has_elevator and a.has_parking and a.neighborhood == "Sol"
    assert b.property_type == PropertyType.PENTHOUSE and b.price == 650000
