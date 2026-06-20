# LLM.md — technical context for agent-assisted work

Context for a coding agent or contributor working on this repo. Read with
`AGENTS.md` (the format spec) and `README.md` (the findings).

## What this project is

An empirical study of high-confidence failures ("breaks") on Polymarket,
and a pressure-test of the functionSPACE distributional-payoff design
against those failures. This repo is the data and code; the writeup lives
separately.

## Pipeline shape

```
Gamma API ─┐
           ├─► data/resolved_markets.csv ──► data/markets_with_snapshots.csv ──► output/polymarket_breaks_dataset.csv ──► results + charts
CLOB API ──┘   (fetch.fetch_resolved_markets)   (fetch.fetch_snapshots)            (transform.build_dataset)              (analysis.*, notebook 03)
   raw                  raw                            raw+snapshots                   analysis-ready
```

- `data/` is gitignored and fetched at runtime.
- `output/polymarket_breaks_dataset.csv` is committed but regenerable: it
  is the deterministic output of `transform.build_dataset()` on the cached
  snapshots.

## Critical conventions (get these wrong and numbers drift)

- **Side / price convention.** Every market is a binary with a YES token
  and a NO token. We store and snapshot the YES price. A market "resolved
  YES" if the YES token settled near 1, "NO" if near 0 (`fetch._infer_resolution`).
- **Break definition.** High confidence on the YES side is YES price > 0.95;
  on the NO side it is YES price <= 0.05. A break is high confidence that
  resolved the other way. The rule is inclusive at the 0.05 boundary (this
  is why the headline core count is 540, not the strict-inequality 528).
  Defined once in `utils.HIGH_CONFIDENCE` / `utils.BREAK_FLOOR`.
- **Break confidence** is the *wrong-side* price: for a NO resolution the
  highest YES price seen above 0.95; for a YES resolution `1 - (lowest YES
  price seen at or below 0.05)`. So it is always in (0.95, 1.0] for a real
  break. See `transform.break_confidence`.
- **Wrong-side exposure is an UPPER BOUND.** `market_volume * wrong_side_price`.
  Volume counts both sides of the book and earlier lower-confidence trades,
  so this overstates realized trader loss. Never present it as money lost.
  See the docstring on `transform.wrong_side_exposure`.
- **Category** comes from the platform when present, else inferred by the
  regex rules in `utils._RULES` (priority order matters: Politics before
  Tech, etc). The `category_source` column records which. Changing the rules
  changes the per-category counts and the bracket count, so the rules are
  frozen to reproduce the published figures.
- **Bracket pattern** is mechanical (`utils.bracket_pattern`):
  `crypto_price_bracket`, `musk_tweet_bracket`, or `other`. The first two
  are the model-failure cohort. This is the structural finding, so its
  definition is load-bearing.
- **Iran cluster** is keyword-detected (`utils.is_iran_cluster`) and
  excluded from all core figures. It is one event across 12 contracts.

## Denominators

The break *rate* needs the full high-confidence cohort, which lives in the
snapshot file, not the breaks dataset. So `analysis.break_rate` and
`analysis.relative_risk` take the SNAPSHOT rows, while the descriptive
functions (`sample_summary`, `by_category`, etc) take the analysis-ready
dataset. Do not compute a rate from the breaks file alone; the denominator
is not in it.

## API gotchas

- Gamma `/events` caps `offset` at 10,000 (HTTP 422). `fetch` chunks the
  pull by month to stay under it. A single month that still exceeds the cap
  would need finer chunking (the fetcher warns when it happens).
- CLOB `prices-history` needs `fidelity=720` for resolved markets and
  returns 12-hour bins. Finer granularity is not available post-resolution,
  so breaks that happened entirely inside the final 12 hours are invisible;
  counts are a floor.
- Both endpoints rate-limit. `_http_get_json` sleeps and backs off on 429.
- The snapshot stage is the slow one. The original project ran it with
  parallel workers in ~6 hours; `fetch.fetch_snapshots` here is sequential
  and resumable. A parallel version exists in the project history.

## Hand classification

`output/top40_classifications.csv` holds surprise-type labels that cannot
be assigned mechanically. It has a `status` column (`verified` / `proposed`
/ `needs review`). Per the format spec, the writeup may only lean on
`verified` rows. Some rows concern very recent events and are still pending
verification against primary sources; do not present those as settled.

## Open questions / future work

- Realized trader loss (not the exposure upper bound) would need
  address-level trade data, not pulled here.
- The regression-toward-the-prior pressure the distributional design
  carries (its own most consequential open problem) is best studied by
  simulating trader response under the constant spread. This repo is the
  empirical precursor: it characterizes the real tail-outcome conditions
  such a simulation would model. The simulation itself is out of scope.
