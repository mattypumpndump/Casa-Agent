---
name: intake
description: Turn the client's chat messages into structured SearchParams. Used before every search.
---

# Intake

Read the conversation (and MEMORY.md standing preferences) and call the `set_search_params`
tool exactly once with the best interpretation.

## Rules
- "we are 4", "family of 3", "couple" → household_size. A couple is 2.
- Infer min_bedrooms from household size when not stated: 1 person → 0–1, couple → 1,
  3–4 people → 2–3, 5+ → 3+.
- Rent prices are per month, buy prices are totals. "650k" = 650 000.
- Map informal zone names to official districts using CONTEXT/district_aliases.md
  ("Malasaña" → Centro). Keep the client's wording in `notes`.
- Weights (0–1, sum ≈ 1): budget-focused → weight_price up; "must be near X" →
  weight_location up; many must-haves → weight_amenities up; "space", "big" → weight_size up.
- Refinements apply on top of the previous parameters: "cheaper" lowers max_price ~10 %,
  "add Retiro" extends districts, "drop the terrace" clears needs_terrace.
- If MEMORY.md has a standing preference the client didn't contradict, apply it.
- If something essential is missing (operation, budget), use sensible defaults and write
  "ASSUMED: …" in `notes` so the survey can say what was assumed.
