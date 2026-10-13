"""Shared helpers for HTML scrapers.

The portals change markup often and class names are unstable, so the
adapters here don't rely on CSS classes. Instead they:
  1. find anchors whose href matches the portal's listing-URL pattern,
  2. walk up to the smallest ancestor that contains a price ("€"),
  3. regex the facts out of that card's visible text.
That survives most redesigns as long as URLs and wording stay similar.
"""
from __future__ import annotations

import re

import httpx
from bs4 import BeautifulSoup, Tag

from .. import config
from .base import SourceError

_HEADERS = {
    "User-Agent": config.USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
    "Cache-Control": "no-cache",
}


async def fetch_html(url: str, source: str) -> str:
    try:
        async with httpx.AsyncClient(timeout=config.SCRAPE_TIMEOUT, follow_redirects=True, headers=_HEADERS) as client:
            r = await client.get(url)
    except httpx.HTTPError as exc:
        raise SourceError(f"{source}: request failed ({exc.__class__.__name__})") from exc
    if r.status_code in (403, 429, 503):
        raise SourceError(f"{source}: blocked (HTTP {r.status_code}). Try the Playwright fallback or a different IP.")
    if r.status_code != 200:
        raise SourceError(f"{source}: HTTP {r.status_code}")
    low = r.text[:4000].lower()
    if "captcha" in low or "access denied" in low or "robot" in low and "challenge" in low:
        raise SourceError(f"{source}: anti-bot challenge page returned")
    return r.text


def listing_cards(html: str, href_pattern: str) -> list[tuple[str, str]]:
    """Return [(href, card_text)] for each unique listing link on the page."""
    soup = BeautifulSoup(html, "html.parser")
    rx = re.compile(href_pattern)
    seen: set[str] = set()
    out: list[tuple[str, str]] = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if not rx.search(href):
            continue
        key = rx.search(href).group(0)
        if key in seen:
            continue
        card = _enclosing_card(a)
        if card is None:
            continue
        seen.add(key)
        out.append((href, _text(card)))
    return out


def _enclosing_card(a: Tag) -> Tag | None:
    node: Tag | None = a
    for _ in range(8):
        if node is None:
            return None
        txt = node.get_text(" ", strip=True)
        if "€" in txt and len(txt) < 3000:
            return node
        node = node.parent
    return None


def _text(node: Tag) -> str:
    return re.sub(r"\s+", " ", node.get_text(" ", strip=True))


def euro(text: str) -> float | None:
    """'2.850 €', '2600 €/month', '650.000€' → float."""
    m = re.search(r"(\d{1,3}(?:[.\s]\d{3})+|\d+)(?:,(\d+))?\s*€", text)
    if not m:
        return None
    whole = re.sub(r"[.\s]", "", m.group(1))
    return float(whole + ("." + m.group(2) if m.group(2) else ""))


def first_int(pattern: str, text: str) -> int | None:
    m = re.search(pattern, text, re.I)
    return int(m.group(1)) if m else None


def first_float(pattern: str, text: str) -> float | None:
    m = re.search(pattern, text, re.I)
    return float(m.group(1).replace(",", ".")) if m else None
