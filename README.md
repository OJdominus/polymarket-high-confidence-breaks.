# Surprise Events and Tail Probabilities

An empirical study of where high-confidence prices fail on Polymarket. Of 247,367 resolved markets (January 2024 to April 2026), 540 broke above 95% confidence, carrying roughly $120M in wrong-side capital exposure. Half of that exposure sits in one structural pattern: bracket markets that discretize a numerical outcome into range-buckets.

## Key findings

- High-confidence prices are usually right. Of the 63,453 markets that reached 95% confidence, 540 broke, a rate near 0.85%.
- The rate is not uniform. Bracket markets on a numerical outcome (crypto price ranges, weekly tweet-count ranges) break at about 1.2%, against 0.8% for all other high-confidence markets: a relative rate near 1.6x on more than 9,000 bracket observations.
- Multi-outcome structure alone carries no penalty: negRisk constituents and standalone binaries break at indistinguishable rates.
- Concentration: 113 bracket markets are 21% of the breaks but 51% of the wrong-side exposure.
- Direction: 85% of breaks were dismissed outcomes landing (priced NO, resolved YES), not confident favorites collapsing.

## Quickstart

```bash
pip install -r requirements.txt
python build_notebooks.py
jupyter nbconvert --to notebook --execute notebooks/01-data-collection.ipynb
jupyter nbconvert --to notebook --execute notebooks/02-analysis.ipynb
jupyter nbconvert --to notebook --execute notebooks/03-results.ipynb
```

Notebook 01 fetches and caches the raw data from the Polymarket APIs. The first run of the snapshot stage takes a few hours (one to two API calls per market across ~247K markets); every run after that loads from the `data/` cache in seconds and needs no network. Notebooks 02 and 03 run offline once the cache exists.

## Methodology

**Data source.** Polymarket Gamma API (resolved events) and CLOB API (price history). Sample: every resolved market with at least $10,000 in event volume that closed between January 2024 and April 2026.

**Snapshots.** Each market is snapshotted at three points before resolution: the final pre-close bin, the bin nearest 24 hours before close, and the bin nearest 7 days before close. CLOB price history for resolved markets is available at 12-hour granularity (`fidelity=720`), which sets the floor on how early a break can be detected.

**Break rule.** A market broke if its YES price exceeded 0.95 at any snapshot and it resolved NO, or sat at or below 0.05 and resolved YES. The rule is inclusive at the boundary; the strict-inequality variant (528 core markets) is reported as a robustness check and changes no finding.

**Wrong-side exposure.** Cumulative market volume times the loss per share at the confident-side price. This is an **upper bound** on realized trader losses, not a measure of them: market volume counts both sides of the book and earlier trades at lower confidence. It is labeled as a bound wherever it appears.

**Iran cluster.** Twelve constituent markets resolving on the February 2026 strike cascade are one underlying event across many contracts. They carry roughly $196M, more than the rest of the sample combined, so they are reported separately and excluded from all core figures.

**Classification.** Category and structural pattern are assigned mechanically in code (`src/utils.py`, `src/transform.py`). Surprise-type classification, which requires human judgment, lives in a separate versioned file (`output/top40_classifications.csv`) with a `status` column; only `verified` rows are leaned on in the writeup.

## Reproducing every figure

Every number in the writeup is produced by shipped code from the raw pull. Headline claims map to functions in `src/analysis.py`, all called in `notebooks/02-analysis.ipynb`:

| Claim | Function |
|---|---|
| 540 core breaks, $120M exposure | `analysis.sample_summary` |
| 0.85% break rate (with denominator) | `analysis.break_rate` |
| 1.6x bracket relative risk | `analysis.relative_risk` |
| 113 brackets = 21% / 51% | `analysis.bracket_concentration` |
| 85% dismissed outcomes landing | `analysis.direction_split` |
| Per-category counts and exposure | `analysis.by_category` |
| Threshold sensitivity | `analysis.threshold_sensitivity` |
| 528 strict-boundary robustness | `analysis.boundary_robustness` |

Charts are produced in `notebooks/03-results.ipynb` and saved to `output/`.

## Files

```
.
├── AGENTS.md                       project format spec (for agent-assisted work)
├── LLM.md                          technical context: conventions, gotchas, open questions
├── README.md                       this file
├── requirements.txt
├── build_notebooks.py              generates notebooks/*.ipynb from Python
├── notebooks/
│   ├── 01-data-collection.ipynb    fetch + cache raw data
│   ├── 02-analysis.ipynb           raw -> analysis-ready + every result
│   └── 03-results.ipynb            charts
├── src/
│   ├── fetch.py                    Gamma + CLOB fetching, check-before-fetch caching
│   ├── transform.py                raw -> analysis-ready dataset (selection, derivation, labels)
│   ├── analysis.py                 pure analysis functions; rates expose numerator + denominator
│   └── utils.py                    thresholds, category rules, shared helpers
├── data/                           gitignored; raw + intermediate cache
└── output/                         committed; charts, result tables, analysis-ready dataset
    ├── polymarket_breaks_dataset.csv
    └── top40_classifications.csv
```

## Note on the data files

`output/polymarket_breaks_dataset.csv` is committed as a convenience for anyone who wants to query the results without re-running the fetch. It is regenerable: delete it and run notebook 02, and `build_dataset()` rebuilds it identically from the cached raw data. The full 247K-row raw pull is not committed (it is fetched at runtime).
