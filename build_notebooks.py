"""
Build the analysis notebooks from Python source.

Hand-editing .ipynb JSON is error-prone and produces unreadable diffs, so
the notebook content is authored here and the .ipynb files are generated.
Run whenever notebook content changes:

    python build_notebooks.py

Requires nbformat (in requirements.txt). After generating, the notebooks
execute top-to-bottom:

    jupyter nbconvert --to notebook --execute notebooks/01-data-collection.ipynb
    jupyter nbconvert --to notebook --execute notebooks/02-analysis.ipynb
    jupyter nbconvert --to notebook --execute notebooks/03-results.ipynb
"""

from pathlib import Path
import nbformat as nbf

HERE = Path(__file__).resolve().parent
NB = HERE / "notebooks"
NB.mkdir(exist_ok=True)


def md(text):
    return nbf.v4.new_markdown_cell(text)


def code(src):
    return nbf.v4.new_code_cell(src)


def save(nb, name):
    nb.metadata["kernelspec"] = {
        "display_name": "Python 3", "language": "python", "name": "python3"
    }
    nb.metadata["language_info"] = {"name": "python"}
    with (NB / name).open("w") as f:
        nbf.write(nb, f)
    print(f"wrote {NB / name}")


PATH_BOOT = (
    "import sys\n"
    "from pathlib import Path\n"
    "sys.path.insert(0, str(Path('..').resolve()))"
)


# ---------------------------------------------------------------------------
# 01 - Data collection
# ---------------------------------------------------------------------------

nb = nbf.v4.new_notebook()
nb.cells = [
    md("# 01 — Data collection\n\n"
       "**Purpose:** fetch and cache the raw Polymarket data.\n\n"
       "**Inputs:** Polymarket Gamma and CLOB APIs (network, first run only).\n\n"
       "**Outputs:** `data/resolved_markets.csv`, `data/markets_with_snapshots.csv`.\n\n"
       "**Prerequisites:** none.\n\n"
       "Both fetches are check-before-fetch: if the cache files already exist "
       "they load instantly and no network call is made. The snapshot stage is "
       "the slow one (one to two API calls per market across ~247K markets), so "
       "the first run takes hours; every run after is seconds."),
    code(PATH_BOOT),
    code("from src.fetch import fetch_resolved_markets, fetch_snapshots"),
    md("### Stage 1 — resolved markets (Gamma)\n"
       "Every resolved market with at least $10,000 event volume that closed "
       "in the sample window, chunked by month to avoid the 10,000-offset cap."),
    code("raw_path = fetch_resolved_markets()\n"
         "print(raw_path)"),
    md("### Stage 2 — price snapshots (CLOB)\n"
       "Three pre-resolution YES-price snapshots per market (7d, 24h, final "
       "bin), at 12-hour granularity. Resumable; safe to re-run."),
    code("snap_path = fetch_snapshots()\n"
         "print(snap_path)"),
    md("Raw data is now cached in `data/` (gitignored). Continue to `02-analysis`."),
]
save(nb, "01-data-collection.ipynb")


# ---------------------------------------------------------------------------
# 02 - Analysis
# ---------------------------------------------------------------------------

nb = nbf.v4.new_notebook()
nb.cells = [
    md("# 02 — Analysis\n\n"
       "**Purpose:** turn raw snapshots into the analysis-ready dataset and "
       "compute every headline result.\n\n"
       "**Inputs:** `data/markets_with_snapshots.csv` (from notebook 01).\n\n"
       "**Outputs:** `output/polymarket_breaks_dataset.csv`, plus result "
       "tables in `output/`.\n\n"
       "**Prerequisites:** run `01-data-collection` first.\n\n"
       "The dataset is rebuilt here from cached raw by `build_dataset()`. "
       "Delete the committed CSV and re-run: you get the same file back."),
    code(PATH_BOOT),
    code("import csv\n"
         "from src.transform import build_dataset\n"
         "from src import analysis as A\n"
         "from src.utils import bracket_pattern, infer_category, SNAPSHOTS"),
    md("### Rebuild the analysis-ready dataset from raw\n"
       "This is the transform step: selection rule, derived columns, "
       "mechanical labels. It writes `output/polymarket_breaks_dataset.csv`."),
    code("dataset = build_dataset(write=True)\n"
         "print(f'{len(dataset)} breaks in the dataset')"),
    md("### Sample composition\n"
       "Full sample, core sample (Iran cluster removed), and the cluster itself."),
    code("summary = A.sample_summary(dataset)\n"
         "for k, v in summary.items():\n"
         "    print(f'{k:>22}: {v:,.0f}' if 'usd' in k else f'{k:>22}: {v}')"),
    md("### Direction of breaks\n"
       "Dismissed outcomes landing (NO that resolved YES) versus confident "
       "favorites collapsing (YES that resolved NO)."),
    code("A.direction_split(dataset)"),
    md("### Break RATE and the denominator\n"
       "The rate is breaks divided by every market that reached high "
       "confidence, so it needs the snapshot rows, not just the breaks. The "
       "function returns both counts."),
    code("snaps = list(csv.DictReader(open(SNAPSHOTS, encoding='utf-8')))\n"
         "A.break_rate(snaps)"),
    md("### Relative risk: bracket markets versus everything else\n"
       "The structural finding. Bracket markets on a numerical outcome break "
       "at a higher rate than all other high-confidence markets."),
    code("def is_bracket(r):\n"
         "    cat = (r.get('category') or '').strip() or infer_category(\n"
         "        f\"{r.get('event_title','')} {r.get('market_question','')}\")\n"
         "    return bracket_pattern(cat, r.get('event_title',''),\n"
         "                           r.get('market_question','')) != 'other'\n"
         "A.relative_risk(snaps, is_bracket)"),
    md("### Concentration\n"
       "Bracket-pattern markets as a share of break count and of exposure."),
    code("A.bracket_concentration(dataset)"),
    md("### Breakdowns by category and structural pattern"),
    code("by_cat = A.by_category(dataset)\n"
         "for r in by_cat:\n"
         "    print(f\"{r['category']:<14}{r['breaks']:>5}  ${r['exposure_usd']/1e6:>6.1f}M\")"),
    code("A.by_bracket_pattern(dataset)"),
    md("### Robustness: confidence threshold and the boundary rule"),
    code("A.threshold_sensitivity(snaps)"),
    code("A.boundary_robustness(snaps)"),
    md("### Save result tables\n"
       "Small summary tables are committed to `output/`; raw data is not."),
    code("import csv as _csv\n"
         "from src.utils import OUTPUT_DIR\n"
         "OUTPUT_DIR.mkdir(exist_ok=True)\n"
         "with open(OUTPUT_DIR / 'by-category.csv', 'w', newline='') as f:\n"
         "    w = _csv.DictWriter(f, fieldnames=by_cat[0].keys()); w.writeheader(); w.writerows(by_cat)\n"
         "print('wrote output/by-category.csv')"),
]
save(nb, "02-analysis.ipynb")


# ---------------------------------------------------------------------------
# 03 - Results / charts
# ---------------------------------------------------------------------------

nb = nbf.v4.new_notebook()
nb.cells = [
    md("# 03 — Results\n\n"
       "**Purpose:** the charts behind the writeup.\n\n"
       "**Inputs:** `output/polymarket_breaks_dataset.csv` (from notebook 02).\n\n"
       "**Outputs:** chart PNGs in `output/`.\n\n"
       "**Prerequisites:** run `02-analysis` first.\n\n"
       "Charts are saved at >=150 DPI with titles, axis labels, and legends. "
       "Re-running regenerates them identically."),
    code(PATH_BOOT),
    code("import matplotlib\n"
         "matplotlib.use('Agg')\n"
         "import matplotlib.pyplot as plt\n"
         "from src.transform import build_dataset\n"
         "from src import analysis as A\n"
         "from src.utils import OUTPUT_DIR\n"
         "dataset = build_dataset(write=False)"),
    md("### Figure: bracket concentration\n"
       "Share of broken markets versus share of wrong-side exposure."),
    code("conc = A.bracket_concentration(dataset)\n"
         "bp = {r['pattern']: r for r in A.by_bracket_pattern(dataset)}\n"
         "labels = ['Crypto price brackets', 'Musk tweet brackets', 'All other']\n"
         "keys = ['crypto_price_bracket', 'musk_tweet_bracket', 'other']\n"
         "share_n = [bp.get(k, {'breaks_pct':0})['breaks_pct'] for k in keys]\n"
         "share_e = [bp.get(k, {'exposure_pct':0})['exposure_pct'] for k in keys]\n"
         "colors = ['#2f6bff', '#9aa3b2', '#dde3ec']\n"
         "fig, ax = plt.subplots(figsize=(9, 3.6))\n"
         "for yi, shares in enumerate([share_n, share_e]):\n"
         "    left = 0\n"
         "    for v, c in zip(shares, colors):\n"
         "        ax.barh(1-yi, v, left=left, color=c, edgecolor='white')\n"
         "        if v > 0.04: ax.text(left+v/2, 1-yi, f'{v*100:.0f}%', ha='center', va='center', fontweight='bold')\n"
         "        left += v\n"
         "ax.set_yticks([1, 0]); ax.set_yticklabels(['Share of broken markets', 'Share of exposure'])\n"
         "ax.set_xlim(0, 1); ax.set_title('Bracket compression carries half the cost')\n"
         "ax.legend(labels, loc='lower center', bbox_to_anchor=(0.5, -0.35), ncol=3, frameon=False)\n"
         "fig.savefig(OUTPUT_DIR / '01-bracket-concentration.png', dpi=200, bbox_inches='tight')\n"
         "print('saved output/01-bracket-concentration.png')"),
    md("### Figure: category divergence\n"
       "Share of breaks versus share of exposure, by category."),
    code("cats = A.by_category(dataset)\n"
         "N = sum(c['breaks'] for c in cats); E = sum(c['exposure_usd'] for c in cats)\n"
         "names = [c['category'] for c in cats]\n"
         "import numpy as np\n"
         "y = np.arange(len(cats))[::-1]\n"
         "fig, ax = plt.subplots(figsize=(9, 5))\n"
         "ax.barh(y+0.2, [-c['breaks']/N for c in cats], height=0.38, color='#9aa3b2', label='Share of breaks')\n"
         "ax.barh(y-0.2, [c['exposure_usd']/E for c in cats], height=0.38, color='#2f6bff', label='Share of exposure')\n"
         "ax.set_yticks(y); ax.set_yticklabels(names); ax.axvline(0, color='black', lw=0.8)\n"
         "ax.set_xticks([-.4,-.2,0,.2,.4]); ax.set_xticklabels(['40%','20%','0%','20%','40%'])\n"
         "ax.set_title('Frequency and cost rank categories differently'); ax.legend(frameon=False)\n"
         "fig.savefig(OUTPUT_DIR / '02-category-divergence.png', dpi=200, bbox_inches='tight')\n"
         "print('saved output/02-category-divergence.png')"),
    md("### Figure: threshold sensitivity"),
    code("import csv\n"
         "from src.utils import SNAPSHOTS\n"
         "snaps = list(csv.DictReader(open(SNAPSHOTS, encoding='utf-8')))\n"
         "ts = A.threshold_sensitivity(snaps)\n"
         "fig, ax = plt.subplots(figsize=(8, 4))\n"
         "xs = [f\">{int(t['threshold']*100)}%\" for t in ts]\n"
         "ax.bar(xs, [t['breaks'] for t in ts], color='#2f6bff')\n"
         "for i, t in enumerate(ts): ax.text(i, t['breaks']+10, f\"{t['breaks']:,}\", ha='center', fontweight='bold')\n"
         "ax.set_ylabel('Broken markets'); ax.set_title('Sensitivity to the confidence threshold')\n"
         "fig.savefig(OUTPUT_DIR / '03-threshold-sensitivity.png', dpi=200, bbox_inches='tight')\n"
         "print('saved output/03-threshold-sensitivity.png')"),
]
save(nb, "03-results.ipynb")

print("\nall notebooks built. execute with:")
print("  jupyter nbconvert --to notebook --execute notebooks/01-data-collection.ipynb")
print("  jupyter nbconvert --to notebook --execute notebooks/02-analysis.ipynb")
print("  jupyter nbconvert --to notebook --execute notebooks/03-results.ipynb")
