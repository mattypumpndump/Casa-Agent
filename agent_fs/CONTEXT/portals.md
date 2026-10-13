# CONTEXT/portals.md — Source notes

| Source | Access | Covers | Notes |
|---|---|---|---|
| idealista | Official API, needs key (developers.idealista.com) | rent + buy | Most complete; free tier is ~100 req/month, so cache. |
| spotahome | Scraper, no key | rent (furnished, mid/long-term) | Server-rendered HTML; rooms and whole flats; "From <date>" availability. |
| habitaclia | Scraper, no key | rent + buy | 15 listings/page; card text "106m2 - 3 habitaciones - 2 baños". |
| pisos | Scraper, no key | rent + buy | Blocks plain HTTP from many networks → CASA_BROWSER_FALLBACK=1 (Playwright). |
| fotocasa | Scraper, no key | rent + buy | JSON in window.__INITIAL_PROPS__; frequently blocked. |
| demo | Built-in | rent + buy | Synthetic Madrid data; links go to the portal's real search for that zone. |

Dedup matches the same property across portals by beds/baths, size ±4 %, price ±8 %, and location (coords < 150 m, or same address, or same neighbourhood).
