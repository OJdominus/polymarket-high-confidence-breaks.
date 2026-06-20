# AGENTS.md — Analysis Project Format

> Drop this file at the root of your analysis repo. Your coding agent should read it
> in full before scaffolding or editing anything, and follow it as the house style for
> data-analysis projects. It is self-contained: it assumes no external files, agents,
> or conventions beyond what is written here.

This describes a reproducible data-analysis format built around prediction-market
research. The goal is a repo where **anyone can clone it, run it top to bottom, and
regenerate every number and chart in the writeup from raw data** — no orphan artifacts,
no manual steps, no "trust me" tables.

---

## Core principles

1. **Notebooks are narrative; `src/` does the work.** Notebooks tell the story
   (markdown + a few cells calling into `src/` + charts). Any function worth reusing
   lives in a `src/` module, not pasted into a cell.
2. **Every figure in the writeup is regenerable by shipped code from the raw pull.**
   If the writeup cites a number, there is a code path in this repo that produces it
   starting from the raw data. No statistic exists only inside a CSV you can't rebuild.
3. **Data is never committed.** It is fetched at runtime and cached locally; `data/` is
   gitignored. Charts and small result tables in `output/` *are* committed.
4. **Check-before-fetch.** Every fetch checks the local cache first, so the second run
   is instant and offline-friendly.
5. **Runs top-to-bottom unattended.** No interactive widgets that block, no hardcoded
   absolute paths, no cell that needs a prior manual step.

---

## Folder structure

```
<project>/
├── AGENTS.md                  # this file
├── notebooks/
│   ├── 01-data-collection.ipynb   # fetch + cache raw data
│   ├── 02-analysis.ipynb          # transform raw → analysis-ready + compute results
│   └── 03-results.ipynb           # charts + narrative findings
├── src/
│   ├── __init__.py
│   ├── fetch.py               # API/data fetching, with check-before-fetch caching
│   ├── transform.py           # raw → analysis-ready dataset (THE step people skip)
│   ├── analysis.py            # pure analysis functions (stats, aggregations)
│   └── utils.py               # constants, config, small transforms
├── build_notebooks.py         # generates notebooks/*.ipynb from Python (see below)
├── data/                      # gitignored — cached raw + intermediate data
│   └── .gitkeep
├── output/                    # committed — charts (.png) and result tables (.csv)
├── requirements.txt
├── README.md                  # findings + quickstart + methodology
├── LLM.md                     # technical context for agent-assisted work
└── .gitignore
```

If there are more than three logical stages, add `04-...`, `05-...` notebooks. Keep the
numbering = run order.

---

## The transform step is mandatory (read this twice)

The single most common reproducibility failure is shipping the **raw fetchers** and the
**final analysis-ready dataset**, but *not* the code that turns one into the other. When
that middle step is missing, every headline number becomes unverifiable — a reviewer can
re-query the final CSV but cannot confirm how rows were selected, how exposure/scores
were computed, or how labels were assigned.

**Rule: `src/transform.py` (or a clearly-named notebook stage) must take the raw pull and
deterministically produce the analysis-ready dataset.** This includes:

- the selection/filter rule (what counts as in-sample, with the exact threshold),
- every derived column (how each metric is computed, with the formula in the docstring),
- every label/classification (mechanical rules in code; hand-classification in a
  separate, versioned file with a `status` column — see "Hand classification" below).

The analysis-ready CSV may be committed as a convenience, but it must be **regenerable**:
`python build_notebooks.py && jupyter nbconvert --execute notebooks/02-analysis.ipynb`
rebuilds it from cached raw data. If you delete the committed CSV and re-run, you get the
same file back.

---

## Notebook rules

Every notebook starts with a markdown header cell:

```markdown
# <Notebook Title>

**Purpose:** what this notebook does
**Inputs:** data it reads (cache files, prior notebook outputs)
**Outputs:** what it produces (cache files, charts, tables)
**Prerequisites:** which notebooks must run first
```

Then:

- **Import from `src/`** — no substantial logic in cells. A few exploratory lines are
  fine; anything reusable goes to `src/`.
- **Relative paths only:**
  ```python
  import sys
  from pathlib import Path
  sys.path.insert(0, str(Path("..").resolve()))
  from src.fetch import fetch_resolved_markets
  from src.analysis import break_rate
  ```
- **Check-before-fetch for all data:**
  ```python
  cache = Path("../data/markets.parquet")
  if cache.exists():
      df = pd.read_parquet(cache)
      print(f"loaded {len(df):,} rows from cache")
  else:
      df = fetch_resolved_markets()      # from src/fetch.py
      df.to_parquet(cache)
      print(f"fetched and cached {len(df):,} rows")
  ```
- **Save outputs explicitly:**
  ```python
  fig.savefig("../output/01-break-rate-by-category.png", dpi=200, bbox_inches="tight")
  summary.to_csv("../output/break-rate-summary.csv", index=False)
  ```
- **Charts are labeled:** title, axis labels, legend where relevant; saved ≥150 DPI.

---

## `src/` module rules

**`src/fetch.py`** — all network/data acquisition.
- Each fetch function implements check-before-fetch caching to `data/`.
- API base URLs are module-level constants.
- Rate-limit between calls (`time.sleep`), and back off on HTTP 429.
- Handle network errors with informative messages; never silently return partial data
  without flagging it.
- No API keys in code — read from environment variables, document in README.

**`src/transform.py`** — raw → analysis-ready (see mandatory section above).
- Pure where possible: read raw in, return the analysis-ready frame out.
- Each derived column documented in a docstring with its exact formula.

**`src/analysis.py`** — statistics and aggregations.
- Pure functions: data in, structured results out (dicts / DataFrames, not printed strings).
- No file I/O, no prints.
- Document the method in the docstring: what it computes, assumptions, how to read it.
- **Denominators are first-class.** A rate is `numerator / denominator`; ship a function
  that returns both, not just the ratio. (E.g. a "break rate" must expose the count of
  markets that reached the confidence threshold, not only the breaks.)

**`src/utils.py`** — constants, config, category maps, small shared transforms.

---

## Generating notebooks from Python (`build_notebooks.py`)

Hand-editing `.ipynb` JSON is error-prone and produces unreadable diffs. Instead, author
notebook *content* in a Python builder and generate the `.ipynb` files. This keeps
notebooks diff-reviewable and lets the agent regenerate them deterministically.

```python
"""
Build the analysis notebooks from Python source.
Run whenever notebook content changes:  python build_notebooks.py
"""
from pathlib import Path
import nbformat as nbf

HERE = Path(__file__).resolve().parent
NB = HERE / "notebooks"
NB.mkdir(exist_ok=True)

def md(t):   return nbf.v4.new_markdown_cell(t)
def code(s): return nbf.v4.new_code_cell(s)

def save(nb, name):
    nb.metadata["kernelspec"] = {"display_name": "Python 3", "language": "python", "name": "python3"}
    nb.metadata["language_info"] = {"name": "python"}
    (NB / name).write_text("")          # ensure file exists
    with (NB / name).open("w") as f:
        nbf.write(nb, f)
    print(f"wrote {NB / name}")

# 02 - analysis
nb = nbf.v4.new_notebook()
nb.cells = [
    md("# 02 — Analysis\n\n**Purpose:** ...\n**Inputs:** ...\n**Outputs:** ..."),
    code("import sys; from pathlib import Path\n"
         "sys.path.insert(0, str(Path('..').resolve()))\n"
         "from src.transform import build_dataset\n"
         "from src.analysis import break_rate"),
    code("df = build_dataset()        # regenerates from cached raw\n"
         "df.head()"),
    # ... more cells ...
]
save(nb, "02-analysis.ipynb")
```

Requires `nbformat` (add to `requirements.txt`). The notebooks must still execute
top-to-bottom after generation: `jupyter nbconvert --to notebook --execute notebooks/02-analysis.ipynb`.

---

## Hand classification (when judgment is unavoidable)

Some labels can't be assigned mechanically (e.g. *why* a market broke). For those:

- Keep them in a **separate, versioned CSV** (e.g. `classifications.csv`), one row per
  case, with the case id, the assigned label, **and a `status` column**
  (`verified` / `proposed` / `needs review`).
- **The writeup may only lean on `verified` rows.** If a marquee example in the prose is
  still `needs review` or `proposed` in the file, either verify it or soften the claim to
  match its status. Do not present an unverified classification as established.
- Mechanical labels (rule-based) stay in `src/`; only genuine judgment calls go in the
  hand-classification file.

---

## Reproducibility files

**`.gitignore`**
```
data/
!data/.gitkeep
.ipynb_checkpoints/
__pycache__/
*.pyc
.env
.DS_Store
```

**`requirements.txt`** — generated from actual imports, with lower bounds:
```
pandas>=2.0
pyarrow>=12.0
requests>=2.28
scipy>=1.10
matplotlib>=3.7
nbformat>=5.9
jupyter>=1.0
```

**`README.md`**
```markdown
# <Project Title>

<1–2 sentence headline finding.>

## Key findings
[table or bullets of headline results]

## Quickstart
pip install -r requirements.txt
python build_notebooks.py
jupyter nbconvert --to notebook --execute notebooks/01-data-collection.ipynb
# then 02, 03 in order

Notebook 01 fetches and caches raw data (~N min first run, seconds after).

## Methodology
[data sources, selection rule with exact threshold, how each metric is computed,
key judgment calls]

## Reproducing every figure
[one line per headline number → which notebook/function regenerates it]

## Files
[directory tree with one-line descriptions]
```

**`LLM.md`** — technical context for agent-assisted work: folder map, the
raw→cache→transform→analyze→output pipeline, critical implementation details (id formats,
side/price conventions, threshold definitions), gotchas, and open questions.

---

## Data-rigor standards (these make the analysis credible)

1. **Every numeric claim is reproducible from raw.** If it's in the writeup, a shipped
   code path regenerates it from the raw pull. No number lives only in a hand-made table.
2. **Ship the transform.** Raw fetchers + final dataset is *not* enough — the code that
   connects them is the deliverable (see the mandatory section).
3. **Distinguish data / hypothesis / interpretation.** Verified data carries a source.
   Author intuitions are flagged as hypotheses. Inferences are flagged as interpretation.
4. **Never cite an unread source.** A headline, title, or URL slug is not a source. If you
   can't access the actual content, mark it `[UNVERIFIED — source not accessed]` and don't
   summarize claims from it.
5. **Upper/lower bounds are labeled as such.** If a metric over- or under-states (e.g. an
   exposure proxy that counts both sides of a book), say so in the column docstring and
   in the writeup. Never present a bound as a realized quantity.
6. **State what you excluded and why.** Sample filters, dropped clusters, dedup rules —
   document each with the count removed.
7. **Robustness checks must reproduce.** If the writeup says "excluding borderline cases
   leaves N," that N must fall out of the shipped code on the shipped data, exactly.

---

## Definition of done (checklist)

- [ ] `git clone` → `pip install -r requirements.txt` → run notebooks 01→02→03 with no manual edits.
- [ ] Deleting the committed analysis-ready CSV and re-running regenerates it identically.
- [ ] Every headline number in the writeup maps to a function/notebook cell that produces it.
- [ ] All rates expose both numerator and denominator.
- [ ] Hand-classified claims used in the writeup are `verified` in the classification file.
- [ ] Bound-type metrics are labeled as bounds.
- [ ] `data/` is gitignored; `output/` charts + tables are committed.
- [ ] README "Reproducing every figure" section is complete.
