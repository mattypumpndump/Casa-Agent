"""The agent's core file system (INSTRUCTIONS.md, MEMORY.md, CONTEXT/, PROJECTS/,
MEMORY/, SKILLS/). Everything the agent "knows" beyond the code lives here, so
teammates can change behaviour by editing Markdown, not Python.

Root defaults to <repo>/agent_fs; override with CASA_FS=/path.
"""
from __future__ import annotations

import json
import os
import re
from datetime import date, datetime
from pathlib import Path

from .models import SearchParams, SearchResult

ROOT = Path(os.getenv("CASA_FS") or Path(__file__).resolve().parent.parent / "agent_fs")
INSTRUCTIONS = ROOT / "INSTRUCTIONS.md"
MEMORY_MD = ROOT / "MEMORY.md"
CONTEXT = ROOT / "CONTEXT"
PROJECTS = ROOT / "PROJECTS"
SESSIONS = ROOT / "MEMORY" / "sessions"
SKILLS = ROOT / "SKILLS"


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8") if p.exists() else ""


# ---------------------------------------------------------------- read side


def instructions() -> str:
    return _read(INSTRUCTIONS)


def skill(name: str) -> str:
    """Body of SKILLS/<name>/SKILL.md without the YAML front-matter."""
    txt = _read(SKILLS / name / "SKILL.md")
    return re.sub(r"^---.*?---\s*", "", txt, count=1, flags=re.S)


def context(name: str) -> str:
    return _read(CONTEXT / name)


def zones(city: str = "Madrid") -> dict:
    """District benchmarks from CONTEXT/<city>_zones.json."""
    p = CONTEXT / f"{city.lower()}_zones.json"
    return json.loads(_read(p) or "{}").get("districts", {})


def memory() -> str:
    return _read(MEMORY_MD)


def system_prompt(skill_name: str, extra_context: list[str] = ()) -> str:
    """INSTRUCTIONS.md + MEMORY.md + the skill + any CONTEXT files, joined."""
    parts = [instructions(), "\n# MEMORY.md (standing client preferences)\n" + memory(), skill(skill_name)]
    parts += [f"\n# CONTEXT/{n}\n" + context(n) for n in extra_context]
    return "\n\n".join(p for p in parts if p.strip())


# ---------------------------------------------------------------- write side


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:60] or "search"


def project_dir(params: SearchParams, session_id: str) -> Path:
    d = PROJECTS / f"{_slug(params.operation.value + '-' + params.city + '-' + '-'.join(params.districts[:2]))}-{session_id[:6]}"
    d.mkdir(parents=True, exist_ok=True)
    return d


def save_project(result: SearchResult, session_id: str) -> Path:
    """PROJECTS/<slug>/: params.json, shortlist.json, survey.md (latest), history/."""
    d = project_dir(result.params, session_id)
    (d / "params.json").write_text(result.params.model_dump_json(indent=2), encoding="utf-8")
    (d / "shortlist.json").write_text(
        json.dumps([o.model_dump(mode="json") for o in result.options], ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    (d / "survey.md").write_text(result.survey, encoding="utf-8")
    hist = d / "history"
    hist.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    (hist / f"{stamp}-survey.md").write_text(result.survey, encoding="utf-8")
    return d


def log_turn(session_id: str, user_message: str, result: SearchResult) -> None:
    """Append one JSON line per turn to MEMORY/sessions/<date>-<session>.jsonl."""
    SESSIONS.mkdir(parents=True, exist_ok=True)
    p = SESSIONS / f"{date.today().isoformat()}-{session_id[:8]}.jsonl"
    rec = {
        "ts": datetime.now().isoformat(timespec="seconds"),
        "session": session_id,
        "user": user_message,
        "params": result.params.model_dump(mode="json"),
        "found": result.total_found, "unique": result.after_dedup, "matching": result.matching,
        "sources_failed": result.sources_failed,
        "top": [{"id": o.listing.id, "score": o.score, "price": o.listing.price} for o in result.options[:3]],
    }
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")


def update_memory(params: SearchParams, previous: SearchParams | None) -> None:
    """Keep MEMORY.md's 'Standing preferences' in sync and append what changed."""
    txt = memory()
    if not txt:
        return
    must = [k.replace("needs_", "") for k in ("needs_elevator", "needs_terrace", "needs_parking",
                                               "needs_furnished", "needs_pets", "needs_air_conditioning") if getattr(params, k)]
    fields = {
        "operation": params.operation.value,
        "city": params.city,
        "household_size": str(params.household_size),
        "preferred_districts": ", ".join(params.districts) or "(none yet)",
        "must_haves": ", ".join(must) or "(none yet)",
        "typical_budget": f"€{params.max_price:,.0f}" + ("/month" if params.operation.value == "rent" else "") if params.max_price else "(unknown)",
    }
    for k, v in fields.items():
        txt = re.sub(rf"^- {k}:.*$", f"- {k}: {v}", txt, flags=re.M)

    # Dated note on refinements
    if previous:
        changes = []
        if params.max_price and previous.max_price and params.max_price != previous.max_price:
            changes.append(f"budget {previous.max_price:,.0f} → {params.max_price:,.0f}")
        if set(params.districts) != set(previous.districts):
            changes.append("zones → " + (", ".join(params.districts) or "any"))
        for k in ("needs_elevator", "needs_terrace", "needs_parking", "needs_furnished", "needs_pets", "needs_air_conditioning"):
            if getattr(params, k) != getattr(previous, k):
                changes.append(("added " if getattr(params, k) else "dropped ") + k.replace("needs_", ""))
        if changes:
            note = f"- {date.today().isoformat()}: " + "; ".join(changes)
            txt = txt.replace("(empty — the agent appends dated notes here", note + "\n(empty — the agent appends dated notes here", 1) \
                if "(empty — the agent appends" in txt else txt.rstrip() + "\n" + note + "\n"
    MEMORY_MD.write_text(txt, encoding="utf-8")
