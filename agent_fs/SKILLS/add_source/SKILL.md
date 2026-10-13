---
name: add_source
description: Procedure for adding a new property portal as a source adapter.
---

# Add a portal

1. Check CONTEXT/portals.md — does the portal have an official API? Prefer it.
2. Open the portal's search page in a browser; note (a) the listing-URL pattern,
   (b) exactly how price, size, rooms, baths and location are written on a card,
   (c) whether the page is server-rendered HTML or needs JS.
3. Create `casa_agent/sources/<portal>.py`:
   - subclass `Source`, set `name`
   - build the search URL from `SearchParams`
   - `html = await fetch_html(url, self.name)` (raises SourceError when blocked)
   - `for href, text in listing_cards(html, HREF_PATTERN): ... Listing(...)`
   - parse with `euro()`, `first_int()`, `first_float()` from `_scrape.py`
   - never return a Listing without `price`; use `size_m2=0` only for rooms
4. Register it in `get_sources()` in `sources/base.py`.
5. Add a fixture test in `tests/test_scrapers.py` using verbatim card text from step 2.
6. Add a row to CONTEXT/portals.md and the name to `.env.example`.
7. Keep request volume tiny; one or two pages per search.
