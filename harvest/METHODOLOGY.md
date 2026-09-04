# harvest/METHODOLOGY.md — how to harvest a real, grounded question set

> **Authority for the question-harvest process** (Feature 1), the harvest counterpart of
> `engines/<engine>.md`: `engines/<engine>.md` is the authority for *how to drive one engine*,
> this file is the authority for *how to build the `<questions.csv>` a run consumes*. The
> orchestrator (SKILL STEP A.5) runs this process; recon sub-agents (`harvest-worker`) execute
> Phase A under it; a skeptic sub-agent (`harvest-skeptic`) executes Phase C. The output shape and
> the `harvest.build` CLI are specified in `pipeline/INTERFACES.md §6`.

Harvesting is **agentic, not an algorithm**. Nothing here is an embeddings or keyword-tool
pipeline: agents gather real demand the way the capture side reads real answers — grounded in what
people actually do, adapted by natural-language method, not by selectors or scrapers. Keyword volume
is read the same way — as one observable signal an agent looks at and reasons about, never as the
generator of the set — but it is **fetched from the platforms' own APIs** (`demand/`, INTERFACES §8),
not by driving a keyword tool in a browser: a number that can be re-pulled head-lessly, in a loop,
by a user with no logged-in session. The result is a `query,lens` CSV plus a `<name>_rationale.md`
explaining, per segment, *why these queries*.

---

## 1. Goal

Produce the set of **real user prompts** to measure a brand's AI-answer visibility against: the
queries by which people actually ask assistants for exactly what the product does — across several
**angles** on the product — so the audit shows where the brand surfaces and where competitors are
cited instead. Quality of this input directly determines how meaningful the audit is.

Inputs the orchestrator provides (from STEP A + the wizard): **brand name**, **domain**,
**market/category**, **known competitors** (seed; workers extend), **target count** and **lens
split**, **language(s)**.

## 2. Output contract

- `questions.csv` — header exactly `query,lens`; `lens ∈ {general, branded, comparative}`; commas
  inside a query are quoted; valid CSV. This is the run's input (§3 / SKILL STEP 2).
- `<name>_rationale.md` — per segment: *who we catch, on which observable signals, why this lens*,
  plus the competitors that actually surfaced. So the set is explainable and visibly not invented.
- Optional separate-language file(s) (e.g. `<name>_ru.csv`) when a market has a real
  non-primary-language audience.

Committed to CSV by `python -m harvest.build --out <questions.csv> --brand "<name>"` (INTERFACES §6),
which validates, dedups, guards the lens/brand invariants, and writes the CSV.

## 3. The iron rule — queries must be REAL, not invented

The single biggest risk is fabricating plausible-sounding queries from imagination. **Do not.**
Every candidate must rest on an **observable signal** that people really ask this. This is the
harvest expression of the project's whole thesis (faithfulness to the real surface). Evidence
sources to gather via web search / fetch:

- **Search autocomplete / suggest** for root phrases of the need and the brand/competitors.
- **"People also ask" / "Related searches"** blocks.
- **Reddit** (subreddits matching the audience), **Hacker News**, developer forums, public
  Discord/Telegram quotes — how people phrase the pain in their own words.
- **X/Twitter** discussion around the brand and its competitors.
- **Competitor pages & comparison/review articles** ("X vs Y", "best <category> 2026") — which
  comparisons are really searched.
- **Marketplace/listing/price pages** relevant to the category; region-specific sources for
  non-English slices.
- **Demand APIs** (`demand/`) — Wordstat for Russian, Google Ads Keyword Planner / Bing Webmaster
  for everything else, autocomplete everywhere. **Required for every candidate**; see the gate below.

**Demand gate — every candidate, measured through `demand/`.** A line does not ship until a demand
provider has been *asked* about it and the answer is recorded with its scope. Never a browser, never
a number typed from memory.

1. **Know what you can measure before you start.** `python -m demand.doctor --geo <cc>` names the
   providers live for this locale (`wordstat` for RU/CIS and any Russian-language slice,
   `google_ads` / `bing` worldwide, `suggest` everywhere) and prints exactly what is missing for the
   rest. Its `verdict` decides which of the two gates below you are working under.
2. **Look up the root phrase of the need, not the conversational sentence.** Assistants receive long
   natural prompts no keyword tool will ever show; what you confirm is that the *underlying demand*
   exists.
   ```bash
   .venv/bin/python -m demand.lookup --geo ru --lang ru --phrase "<root>" --related 10
   .venv/bin/python -m demand.expand --seed "<root>" --geo us --lang en --n 60
   ```
3. **Paste the provider's `scope` string into `signal` verbatim** and its `source_url` into
   `source_url`. The scope already carries region, period and pull date — e.g.
   `wordstat api: «контроль качества продаж» — 1 240 показов/мес, Россия, за последние 30 дней
   (снято 2026-08-25)`. Do not paraphrase it; the point is that the figure is re-pullable.
4. **Volume gate (a ruler answered).** Zero or near-zero on the root ⟹ drop the candidate, or reword
   it to a root that does have volume. A low but non-zero number is fine when the intent is
   commercially sharp — say so in `note` rather than silently keeping it.
5. **Presence gate (no ruler for this locale).** When `doctor` reports presence-only, a candidate may
   rest on the autocomplete signal — but the `signal` must say so (the provider's scope string ends
   in `presence only, no volume`). This is a weaker line, and the skeptic (§6, Phase C) weighs it as
   such. It is still an *observed* signal; an unmeasured guess is not.
6. **Young-brand exception.** A `branded` or `comparative` line may rest on a non-volume signal
   (forum thread, comparison article, review page) when the brand is too young to have measurable
   volume — state that explicitly in `signal` instead of shipping an unverified line.

A candidate with **no** signal is dropped or reworded to a found real pattern. Each `QuestionCandidate`
carries its `signal` + `source_url` (INTERFACES §6.1); each rationale segment names the signals seen.

**Phrasing.** Natural, conversational — as typed to an assistant, not keyword-stuffing. Mix forms:
questions ("is X safe to use?"), needs ("run llama 70b cheap gpu"), "best/top" lists. Vary length
and intent. No brand words in `general`.

## 4. Lenses & their invariants

| lens | definition | invariant |
|---|---|---|
| `general` | neutral need, **brand NOT named** | no brand token; no competitor named as the object of comparison. This is the **primary** bucket — the GEO opening lives here (people who don't yet know the brand but search exactly what it does). |
| `branded` | **brand explicitly named** | brand token present. The reputation/sentiment axis (definition, price, trust, "is X legit", setup). |
| `comparative` | **brand vs alternatives**, or a niche "X vs Y" the brand should intrude on | a comparison is present. Two flavors: (1) direct "brand vs rival" where real head-to-heads exist; (2) rival-vs-rival / "alternatives to X" spaces the brand *should* appear in — its **absence there is itself the finding**. |

`harvest.build` enforces the brand token half of these deterministically when `--brand` is passed
(general-with-brand and branded-without-brand are rejected to `errors`); the semantic half
(comparative actually compares; general has no competitor-as-object) is enforced in synthesis.

## 5. Segment taxonomy — the "different angles"

Segments are **derived from the product**, not fixed. Plan them from the inputs before Phase A;
a two-sided product adds a supply segment, a single-sided SaaS may not. Typical angles (adapt):

- **demand — primary use** (`general`): the core job the product does, price/availability shopping,
  no brand in mind. Usually the largest segment.
- **demand — secondary use** (`general`, some `comparative`): an adjacent job the product also serves.
- **supply / two-sided** (`general` + some `branded`): if the product needs providers/sellers/contributors,
  the people on that side ("how to earn/list/become a provider").
- **category / discovery** (`general`): category-level "best <category>" lists where the brand wants
  to appear alongside named players.
- **branded — reputation** (`branded`): the full "I heard of the brand, now what" funnel — what-is,
  price, trust/legit-or-scam, setup, team. Critical for the sentiment axis.
- **comparative — rivals** (`comparative`): the real "brand vs X" head-to-heads **and** rival-vs-rival
  niches the brand should intrude on.
- **regional / language slice**: mirror the buckets in another language where a real audience exists;
  phrase natively, never machine-translated.

## 6. Phases

Run in phases; inside a phase run sub-agents **in parallel**, collect, then synthesize.

### Phase A — parallel grounded recon (one `harvest-worker` per segment)
Spawn one `harvest-worker` per planned segment. Each gets: the product context, this iron rule (§3),
the lens definitions (§4), and its **one** segment focus. Each returns **15–25 `QuestionCandidate`
objects** with `signal` + `source_url` for every one — no prose beyond the JSON. Workers also collect
native-language phrasings if their segment surfaces them.

### Phase B — synthesis (orchestrator)
1. **Merge** all candidate pools.
2. **Dedup by meaning** (not just text) — collapse near-paraphrases to the single strongest.
3. **Drop** anything without a real signal (§3) or that violates its lens definition (§4).
4. **Balance** to the target counts with a deliberate **`general`-tilt**; inside each lens maximize
   intent/segment diversity (not ten near-identical `general` lines).
5. **Enforce lens invariants** (§4); split any non-primary-language slice into its own file.

### Phase C — adversarial skeptic (one–two `harvest-skeptic` agents)
Hand the skeptic the final set + the thesis; it judges **every line KEEP/CUT** with a reason
(sounds invented / real people don't ask this / meaning-duplicate / wrong lens / off-thesis). Accept
the cuts, backfill from the next-strongest distinct Phase-A candidates. **Goal: every shipped query
survives the skeptic.** (This is the trust discipline of moat #3 applied to the input.)

## 7. Balance, counts, language

- Honor the wizard's target count and split; default to a `general`-tilt (that is where the GEO
  opportunity is). A sensible default for ~36 is **16 / 10 / 10** (±2), but scale to the requested N.
- **Language of a query = the language a real person really asks it in.** Do not machine-translate
  for coverage. Keep a distinct-language slice in its own CSV.

## 8. Pre-ship checklist

- [ ] Header exactly `query,lens`; lens values only `{general, branded, comparative}`; valid CSV.
- [ ] `general` has no brand token and no competitor as the object of comparison.
- [ ] `branded` names the brand; `comparative` contains a comparison.
- [ ] No meaning-level duplicates; intent diversity within each lens.
- [ ] Every line rests on an observable signal (reflected in the rationale).
- [ ] Every line passed the demand gate (§3) — a `demand/` provider's `scope` string in `signal`
      (region, period, pull date), or an explicit reason why no ruler applies to it.
- [ ] No hand-typed volume anywhere: every figure came out of a `demand.*` call.
- [ ] Balance ≈ target split with the intended `general`-tilt.
- [ ] Every line survived the skeptic; `harvest.build` reported `errors: []`.
