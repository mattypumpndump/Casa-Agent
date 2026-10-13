"""The agent: turns conversation into SearchParams, runs the pipeline, and
writes the professional survey.

Two LLM calls per search:
  1. intake  — chat history → SearchParams (JSON via tool use)
  2. analyst — SearchResult → Markdown survey

Both have rule-based fallbacks so the app works with no ANTHROPIC_API_KEY
(useful for development and for teammates without keys).
"""
from __future__ import annotations

import json
import logging
import re
from typing import Optional

from . import config, fs
from .models import Operation, PropertyType, ScoredListing, SearchParams, SearchResult
from .pipeline import run_search
from .sources import get_sources

log = logging.getLogger(__name__)

try:
    import anthropic
except ImportError:  # pragma: no cover
    anthropic = None


def _client() -> Optional["anthropic.AsyncAnthropic"]:
    if anthropic and config.ANTHROPIC_API_KEY:
        return anthropic.AsyncAnthropic(api_key=config.ANTHROPIC_API_KEY)
    return None


# ---------------------------------------------------------------- intake

INTAKE_SYSTEM = """You are the intake step of a housing-search agent for Spain.
Read the conversation and extract the user's search parameters.
Call the `set_search_params` tool exactly once with your best interpretation.
Rules:
- If the user says "we are 4" or "family of 3", that is household_size.
- Infer min_bedrooms from household size when not stated (couple → 1, 3-4 people → 2-3, etc.).
- Prices: rent is per month, buy is total. If the user says "1500" for rent, that's max_price=1500.
- Map informal zone names to Madrid districts where possible (e.g. "Malasaña" → district Centro).
- Set weights (0-1, sum ≈ 1) based on what the user emphasises: budget-focused → weight_price high;
  "must be near X" → weight_location high; lists many must-haves → weight_amenities high.
- Put anything you couldn't encode in `notes` so the analyst can consider it.
- If something essential is missing (operation, budget), still call the tool with sensible defaults
  and mention what you assumed in `notes` prefixed with "ASSUMED:".
"""

_PARAM_TOOL = {
    "name": "set_search_params",
    "description": "Set the structured housing search parameters extracted from the conversation.",
    "input_schema": SearchParams.model_json_schema(),
}


async def extract_params(messages: list[dict], previous: SearchParams | None = None) -> SearchParams:
    """messages: [{"role": "user"|"assistant", "content": str}, ...]"""
    client = _client()
    if client is None:
        return _rule_based_params(" ".join(m["content"] for m in messages if m["role"] == "user"), previous)

    sys = fs.system_prompt("intake", ["district_aliases.md"]) or INTAKE_SYSTEM
    if previous:
        sys += f"\nThe previous parameters were:\n{previous.model_dump_json()}\nApply the user's latest message as a refinement of these."
    try:
        resp = await client.messages.create(
            model=config.ANTHROPIC_MODEL,
            max_tokens=1024,
            system=sys,
            tools=[_PARAM_TOOL],
            tool_choice={"type": "tool", "name": "set_search_params"},
            messages=messages,
        )
        for block in resp.content:
            if block.type == "tool_use":
                return SearchParams.model_validate(block.input)
    except Exception as exc:  # noqa: BLE001
        log.warning("LLM intake failed (%s); using rule-based fallback", exc)
    return _rule_based_params(" ".join(m["content"] for m in messages if m["role"] == "user"), previous)


def _rule_based_params(text: str, previous: SearchParams | None) -> SearchParams:
    """Crude regex fallback. Good enough to demo without a key."""
    t = text.lower()
    p = previous.model_copy() if previous else SearchParams()
    if re.search(r"\b(buy|buying|purchas\w*|compr\w*)\b", t):
        p.operation = Operation.BUY
    elif re.search(r"\b(rent|alquil|renting)\b", t):
        p.operation = Operation.RENT
    m = re.search(r"(?:max|under|below|up to|budget|hasta|máximo|maximo)?\s*€?\s*(\d+(?:[.,]\d+)?k|\d{3,4}(?:[.,]\d{3})*)\s*(?:€|eur|euros)?(?:\s*(?:/|per|al)\s*(?:month|mes|mo))?", t)
    if m:
        v = m.group(1).replace(".", "").replace(",", "")
        p.max_price = float(v[:-1].replace(",", ".")) * 1000 if v.endswith("k") else float(v)
    m = re.search(r"(\d)\s*(?:bed|bedroom|hab|dorm|room)", t)
    if m:
        p.min_bedrooms = int(m.group(1))
    m = re.search(r"(\d+)\s*m2|(\d+)\s*m²|(\d+)\s*(?:square )?met", t)
    if m:
        p.min_size_m2 = float(next(g for g in m.groups() if g))
    m = re.search(r"(?:we are|we're|family of|somos|there are)\s*(\d)|(\d)\s*(?:people|personas|of us|adults)", t)
    if m:
        p.household_size = int(next(g for g in m.groups() if g))
        if p.min_bedrooms is None:
            p.min_bedrooms = max(1, -(-p.household_size // 2))
    if re.search(r"\bcouple\b|\bpareja\b", t) and not m:
        p.household_size = 2
        p.min_bedrooms = p.min_bedrooms or 1
    zone_data = fs.zones(p.city) or {d: {"neighborhoods": h} for d, (h, _, _) in __import__("casa_agent.sources.demo", fromlist=["MADRID_ZONES"]).MADRID_ZONES.items()}
    zones = [d for d in zone_data if d.lower() in t]
    for d, info in zone_data.items():
        if any(h.lower() in t for h in info.get("neighborhoods", [])) and d not in zones:
            zones.append(d)
    if zones:
        if previous and re.search(r"\b(add|also|plus|and also|include|también)\b", t):
            p.districts = list(dict.fromkeys(p.districts + zones))
        else:
            p.districts = zones
    p.needs_elevator = p.needs_elevator or bool(re.search(r"elevator|lift|ascensor", t))
    p.needs_terrace = p.needs_terrace or bool(re.search(r"terrace|balcon|terraza", t))
    p.needs_parking = p.needs_parking or bool(re.search(r"parking|garage|garaje", t))
    p.needs_furnished = p.needs_furnished or bool(re.search(r"furnish|amueblad", t))
    p.needs_pets = p.needs_pets or bool(re.search(r"\bpet|dog|cat|mascota|perro|gato", t))
    p.needs_air_conditioning = p.needs_air_conditioning or bool(re.search(r"air ?con|a/c|aire", t))
    # Refinements (only meaningful when there are previous params)
    if previous:
        if re.search(r"cheaper|más barato|mas barato|lower budget|less expensive", t) and p.max_price:
            p.max_price = round(p.max_price * 0.9, -1)
        if re.search(r"bigger|más grande|more space|larger", t):
            p.min_size_m2 = (p.min_size_m2 or 50) * 1.2
        drop = re.search(r"(?:drop|without|no need for|don'?t need|skip|forget|remove)\s+(?:the\s+)?(terrace|parking|elevator|lift|furnish\w*|pets?|air ?con\w*|a/c)", t)
        if drop:
            w = drop.group(1)
            if w.startswith("terr"): p.needs_terrace = False
            elif w.startswith("park"): p.needs_parking = False
            elif w in ("elevator", "lift"): p.needs_elevator = False
            elif w.startswith("furn"): p.needs_furnished = False
            elif w.startswith("pet"): p.needs_pets = False
            else: p.needs_air_conditioning = False
        if re.search(r"\bany(?:where| zone| district)|no zone preference|all zones", t):
            p.districts = []
    if re.search(r"\bstudio\b", t):
        p.property_types = [PropertyType.STUDIO]
    if re.search(r"\bhouse\b|chalet|casa\b", t):
        p.property_types = [PropertyType.HOUSE]
    p.notes = "Parsed without LLM (no ANTHROPIC_API_KEY)."
    return p


# ---------------------------------------------------------------- analyst

ANALYST_SYSTEM = """You are a senior property consultant writing a short, professional survey for a client.
You receive the client's parameters and a ranked shortlist with computed scores, pros, cons and flags.
Write in clear Markdown, in the same language as the client's notes if they are not in English, otherwise English.

Structure:
1. **Executive summary** (3-4 sentences): what the market looks like for these parameters, how many options matched, your top recommendation and why.
2. **Top options** — for each of the best 3-5: a heading with "#N — <title> — €price", one line of key facts
   (beds/baths/m²/zone/€ per m² vs zone average), 2-3 sentences of professional assessment, and the flags
   as a "Check before visiting" line if any. Link the title to the listing URL.
3. **Comparison table** of all shortlisted options: # | Zone | Beds/Baths | m² | Price | €/m² vs zone | Score.
4. **Trade-offs** — 3-5 bullets: what the client would gain by relaxing each constraint (e.g. "+200€ budget unlocks X").
5. **Next steps** — concrete actions (visit order, questions to ask, documents, negotiation points).

Be concrete and honest. Use only facts from the data. Do not invent amenities or neighbourhood claims
not supported by the listing. Keep it under ~700 words."""


async def write_survey(result: SearchResult) -> str:
    client = _client()
    payload = {
        "params": result.params.model_dump(mode="json"),
        "stats": {
            "sources_queried": result.sources_queried,
            "sources_failed": result.sources_failed,
            "total_found": result.total_found,
            "unique_after_dedup": result.after_dedup,
            "matching_filters": result.matching,
        },
        "options": [
            {
                "rank": i + 1,
                "score": o.score,
                "breakdown": o.score_breakdown,
                "pros": o.pros,
                "cons": o.cons,
                "flags": o.flags,
                "listing": o.listing.model_dump(mode="json", exclude={"photos", "lat", "lon"}),
            }
            for i, o in enumerate(result.options)
        ],
    }
    if client is None:
        return _rule_based_survey(result)
    try:
        resp = await client.messages.create(
            model=config.ANTHROPIC_MODEL,
            max_tokens=2500,
            system=fs.system_prompt("survey_writer") or ANALYST_SYSTEM,
            messages=[{"role": "user", "content": "Data:\n```json\n" + json.dumps(payload, ensure_ascii=False, default=str) + "\n```"}],
        )
        return "".join(b.text for b in resp.content if b.type == "text")
    except Exception as exc:  # noqa: BLE001
        log.warning("LLM survey failed (%s); using template", exc)
        return _rule_based_survey(result)


def _fmt_price(o: ScoredListing) -> str:
    l = o.listing
    return f"€{l.price:,.0f}" + ("/month" if l.operation == Operation.RENT else "")


def _rule_based_survey(r: SearchResult) -> str:
    p = r.params
    lines = [f"## Housing survey — {p.summary()}", ""]
    if not r.options:
        lines.append(
            f"No listings matched. {r.after_dedup} unique properties were found across "
            f"{len(r.sources_queried)} source(s) before filters. Try raising the budget, "
            "widening the zones, or relaxing a must-have."
        )
        return "\n".join(lines)
    best = r.options[0]
    lines += [
        f"**Executive summary.** {r.total_found} listings were collected from {len(r.sources_queried)} source(s), "
        f"{r.after_dedup} unique properties after removing cross-portal duplicates, and {r.matching} match your criteria. "
        f"The strongest option is **{best.listing.title}** in {best.listing.district} at {_fmt_price(best)} "
        f"(score {best.score}/100).",
        "",
        "### Top options",
    ]
    for i, o in enumerate(r.options[:5], 1):
        l = o.listing
        vs = f"{l.price_vs_zone_pct:+.0f}% vs zone" if l.price_vs_zone_pct is not None else ""
        lines.append(f"**#{i} — [{l.title}]({l.url}) — {_fmt_price(o)}**  ")
        lines.append(f"{l.bedrooms} bd / {l.bathrooms} ba · {l.size_m2:.0f} m² · {l.district} ({l.neighborhood}) · €{l.price_per_m2:,.0f}/m² {vs}  ")
        if o.pros:
            lines.append("Pros: " + "; ".join(o.pros) + "  ")
        if o.cons:
            lines.append("Cons: " + "; ".join(o.cons) + "  ")
        if o.flags:
            lines.append("Check before visiting: " + "; ".join(o.flags) + "  ")
        lines.append("")
    lines += ["### Comparison", "", "| # | Zone | Bd/Ba | m² | Price | €/m² vs zone | Score |", "|---|---|---|---|---|---|---|"]
    for i, o in enumerate(r.options, 1):
        l = o.listing
        vs = f"{l.price_vs_zone_pct:+.0f}%" if l.price_vs_zone_pct is not None else "–"
        lines.append(f"| {i} | {l.district} | {l.bedrooms}/{l.bathrooms} | {l.size_m2:.0f} | {_fmt_price(o)} | {vs} | {o.score} |")
    lines += ["", "### Next steps", "",
              "1. Visit the top 3 in score order; ask about community fees, renovation history and energy bills.",
              "2. For anything flagged above the zone average, open with an offer 5–8% below asking.",
              "3. Refine this search in the chat (e.g. “cheaper, but I can drop the terrace”)."]
    return "\n".join(lines)


# ---------------------------------------------------------------- top-level


async def chat_turn(messages: list[dict], previous: SearchParams | None = None,
                    source_names: list[str] | None = None, session_id: str = "cli") -> SearchResult:
    """One full turn: extract params, search, write survey, then persist to the
    agent file system (PROJECTS/, MEMORY/sessions/, MEMORY.md)."""
    params = await extract_params(messages, previous)
    sources = get_sources(source_names or config.SOURCES)
    result = await run_search(params, sources)
    result.survey = await write_survey(result)
    try:
        fs.save_project(result, session_id)
        fs.log_turn(session_id, messages[-1]["content"] if messages else "", result)
        fs.update_memory(params, previous)
    except OSError as exc:  # read-only FS etc. — never fail the search over bookkeeping
        log.warning("Could not persist to agent_fs: %s", exc)
    return result
