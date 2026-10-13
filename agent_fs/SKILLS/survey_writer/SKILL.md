---
name: survey_writer
description: Write the professional housing survey from a scored SearchResult. Used after every search.
---

# Survey writer

Input: client parameters, run stats, and the ranked shortlist with score breakdown, pros, cons, flags.
Output: Markdown, under ~700 words, in the client's language.

## Template
1. **Executive summary** (3–4 sentences): market picture for these parameters, how many
   options matched, the top recommendation and why. Mention any source that failed.
2. **Top options** — best 3–5. For each:
   `### #N — [Title](url) — €price`
   one line of facts (beds/baths · m² · zone · €/m² vs zone median),
   2–3 sentences of professional assessment,
   `Check before visiting:` the flags, if any.
3. **Comparison table**: `# | Zone | Bd/Ba | m² | Price | €/m² vs zone | Score`.
4. **Trade-offs** — 3–5 bullets: what relaxing each constraint would unlock
   ("+€200/month unlocks Chamberí", "dropping parking adds 6 options").
5. **Next steps** — visit order, questions to ask, documents to prepare, negotiation points
   (anything ≥15 % above zone median → open 5–8 % below asking).

## Rules
- Facts only; nothing not in the data. "Not stated" is a valid answer.
- Demo listings are synthetic: say so once at the top if any option's source starts with "demo".
- Use the client's name for zones in prose if they used one (Malasaña), the district in tables.
