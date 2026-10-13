# Casa Agent

A housing-search agent for Spain. You describe what you need in plain language; it queries several property portals, merges duplicate listings, scores every option against your parameters (budget, size, zones, household size, must-haves), and writes a professional survey with a ranked shortlist, comparison table, trade-offs and next steps. Then you refine it in the chat ("cheaper", "add Retiro", "I can drop the terrace").

## Quick start (no API keys needed)

```bash
git clone https://github.com/YOUR_USERNAME/casa-agent.git
cd casa-agent
./run.sh            # Windows: run.bat
```

`run.sh` creates the virtual environment, installs everything, writes a default `.env`, starts the server and opens http://127.0.0.1:8000 in your browser. Re-run it any time; Ctrl+C stops the server.

Manual equivalent:

```bash
python3 -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
python -m pip install -r requirements.txt
cp .env.example .env
python -m uvicorn casa_agent.web.app:app --reload
```

Open http://127.0.0.1:8000. Out of the box it runs on the built-in **demo** source (400 synthetic Madrid listings simulating two portals; each links to the portal's real search for that zone) and a rule-based parser, so the whole pipeline works offline. To pull real listings with no API key, set `CASA_SOURCES=demo,spotahome,habitaclia` in `.env`.

Command line instead of the web app:

```bash
python -m casa_agent.cli "We are 3, renting in Chamberí or Retiro, max 1800/month, need an elevator"
```

## Turning on the real thing

Copy `.env.example` to `.env` and fill in what you have:

| Variable | What it enables |
|---|---|
| `ANTHROPIC_API_KEY` | LLM intake (understands any phrasing, infers bedrooms from household, sets weights) and the LLM-written survey. Without it, a regex parser and a template survey are used. |
| `IDEALISTA_API_KEY`, `IDEALISTA_SECRET` | Idealista official API. Register at https://developers.idealista.com/ (free tier is rate-limited). |
| `CASA_SOURCES` | Comma-separated. `demo` (offline), `spotahome` and `habitaclia` (scrapers, no key), `pisos` and `fotocasa` (scrapers, often blocked), `idealista` (API, needs key). Default `demo`. |
| `CASA_BROWSER_FALLBACK=1` | Fetch pisos.com through headless Chromium (Playwright) when plain HTTP is blocked. |
| `CASA_FS` | Path to the agent file system (default `./agent_fs`). |

A source that fails (no key, blocked, site changed) is reported in the UI and the others still run.

## The agent's file system (`agent_fs/`)

The agent's identity, knowledge and memory are files, not code, following the *AI Agent: Core File System* pattern. Teammates change behaviour by editing Markdown.

```
agent_fs/
├── INSTRUCTIONS.md       system persona + operating rules → base of every LLM prompt
├── MEMORY.md             standing client preferences; read before intake, updated after each search
├── CONTEXT/              reference knowledge
│   ├── madrid_zones.json   district benchmarks (€/m²) used by the demo source and scoring sanity checks
│   ├── district_aliases.md "Malasaña" → Centro, etc. (given to the intake prompt)
│   └── portals.md          what each source covers and its quirks
├── PROJECTS/             one folder per search: params.json, shortlist.json, survey.md, history/
├── MEMORY/sessions/      append-only JSONL log of every turn
└── SKILLS/               procedures the agent follows
    ├── intake/SKILL.md       chat → SearchParams rules
    ├── survey_writer/SKILL.md  the survey template and rules
    └── add_source/SKILL.md   how to add a new portal
```

`casa_agent/fs.py` is the only code that touches this tree.

## How it works

```
chat message ──▶ intake agent ──▶ SearchParams
                                     │
     ┌───────────┬───────────┬───────┴────┬───────────┬──────────┐
     ▼           ▼           ▼            ▼           ▼          ▼
 Idealista   Spotahome   Habitaclia   pisos.com   Fotocasa     Demo      (all return Listing)
   (API)     (scrape)     (scrape)     (scrape)    (scrape)
     └───────────┴───────────┴───────┬────┴───────────┴──────────┘
                                     ▼
                     dedup (same flat on 2+ portals → one, cheapest kept)
                                     ▼
                     hard filters (budget, beds, zones, must-haves)
                                     ▼
                     enrich (€/m², vs zone median, days on market)
                                     ▼
                     score (price / size & household fit / location / amenities) + pros, cons, flags
                                     ▼
                     analyst agent ──▶ Markdown survey ──▶ web UI
```

| File | Responsibility |
|---|---|
| `casa_agent/models.py` | The shared schema: `Listing`, `SearchParams`, `ScoredListing`, `SearchResult`. **Everything plugs into this.** |
| `casa_agent/sources/base.py` | `Source` interface + registry. |
| `casa_agent/sources/idealista.py` | Official API client. |
| `casa_agent/sources/fotocasa.py` | Scraper of the JSON embedded in Fotocasa's search page. Fragile by nature. |
| `casa_agent/sources/spotahome.py` | HTML scraper, rent only, no key. |
| `casa_agent/sources/habitaclia.py` | HTML scraper, rent + buy, no key. |
| `casa_agent/sources/pisos.py` | HTML scraper with optional Playwright fallback. |
| `casa_agent/sources/_scrape.py` | Shared helpers: polite fetch with block detection, class-independent card extraction, € parsing. |
| `casa_agent/sources/demo.py` | Synthetic data, deterministic, with cross-portal duplicates. |
| `casa_agent/fs.py` | Reads/writes the `agent_fs/` tree (prompts, memory, projects, logs). |
| `casa_agent/pipeline.py` | Pure functions: fetch_all, dedup, hard_filter, enrich, score, run_search. |
| `casa_agent/agent.py` | Intake (chat → params) and analyst (result → survey), each with an LLM path and a rule-based fallback. |
| `casa_agent/web/app.py` | FastAPI: `POST /api/chat`, `GET /api/health`. In-memory sessions. |
| `casa_agent/web/static/index.html` | Single-page chat + results UI. |
| `tests/` | Unit tests for dedup, filters, enrichment, scoring, parser. `python -m pytest`. |

## Adding a portal (the main way to split work in a team)

Follow `agent_fs/SKILLS/add_source/SKILL.md`. In short:

1. Create `casa_agent/sources/<portal>.py` with a class subclassing `Source`, implementing `async def search(self, params) -> list[Listing]`. Raise `SourceError` on failure instead of returning garbage.
2. Register it in `get_sources()` in `sources/base.py`.
3. Add it to `CASA_SOURCES`.

That's all: dedup, scoring and the UI need no changes.

## Suggested split for a group project

- **Backbone (1 person):** schema, dedup quality (e.g. photo-hash matching), tests.
- **Sources (1–2 people):** more portals (pisos.com, Habitaclia), a Playwright-based fallback for sites that block plain HTTP, caching with a scheduled re-scrape.
- **Enrichment (1 person):** real transit distance (Google/Mapbox/OSM), noise & safety data, school proximity, mortgage estimate for purchases.
- **Agent & UX (1 person):** prompt tuning, a "why this score?" explanation, PDF export of the survey, saved searches with email alerts for new matches.

## Notes on scraping

Portals aggressively block bots and their terms of service generally prohibit scraping. Prefer official APIs where they exist (Idealista has one). The Fotocasa adapter is included as a worked example of the scraping path and may stop working at any time. Keep request volumes tiny and don't run it in a loop.
