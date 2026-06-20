"""
Analysis functions: data in, structured results out.

Every function here is pure. No file I/O, no printing, no charts. Each
takes the analysis-ready rows (from transform.build_dataset) and returns
dicts or lists of dicts that a notebook turns into tables and figures.

Design rule from the project spec: denominators are first-class. A rate is
numerator over denominator, so every rate function returns both counts, not
just the ratio. The break rate, in particular, must expose how many markets
reached the confidence threshold, not only how many broke.
"""

from collections import defaultdict

from src.utils import to_float
from src.transform import is_high_confidence, is_break


# ---------------------------------------------------------------------------
# Helpers.
# ---------------------------------------------------------------------------

def _exposure(row):
    return to_float(row.get("wrong_side_exposure_usd")) or 0.0


def core_rows(dataset):
    """The dataset excluding the Iran cluster (the default analysis sample)."""
    return [r for r in dataset if r.get("in_iran_cluster") != "true"]


def iran_rows(dataset):
    return [r for r in dataset if r.get("in_iran_cluster") == "true"]


# ---------------------------------------------------------------------------
# Headline sample description.
# ---------------------------------------------------------------------------

def sample_summary(dataset):
    """Counts and exposure for the full, core, and Iran-cluster samples."""
    core = core_rows(dataset)
    iran = iran_rows(dataset)
    return {
        "full_breaks": len(dataset),
        "full_exposure_usd": sum(_exposure(r) for r in dataset),
        "core_breaks": len(core),
        "core_exposure_usd": sum(_exposure(r) for r in core),
        "iran_breaks": len(iran),
        "iran_exposure_usd": sum(_exposure(r) for r in iran),
    }


def direction_split(dataset):
    """
    How breaks divide between dismissed outcomes landing (NO->YES) and
    confident favorites collapsing (YES->NO), on the core sample.
    """
    core = core_rows(dataset)
    longshot = sum(1 for r in core if r.get("resolution") == "YES")
    favorite = sum(1 for r in core if r.get("resolution") == "NO")
    n = len(core) or 1
    return {
        "longshot_landed": longshot,
        "longshot_pct": longshot / n,
        "favorite_collapsed": favorite,
        "favorite_pct": favorite / n,
        "total": len(core),
    }


# ---------------------------------------------------------------------------
# Break RATE. This needs the full high-confidence cohort as denominator,
# which lives in the snapshot file, not just the breaks. So this function
# takes the snapshot rows, not the analysis-ready dataset.
# ---------------------------------------------------------------------------

def break_rate(snapshot_rows, exclude_iran=True, predicate=None):
    """
    Break rate = breaks / markets that reached high confidence.

    Returns BOTH counts plus the rate, never the bare ratio. Optionally
    restrict to a subset via `predicate(row) -> bool` (e.g. bracket markets),
    which is how the relative-risk comparison is built.

    Pass the SNAPSHOT rows here (data/markets_with_snapshots.csv loaded as
    dicts), because the denominator is every high-confidence market, not
    only those that broke.
    """
    from src.utils import is_iran_cluster

    denom = num = 0
    for r in snapshot_rows:
        if exclude_iran and is_iran_cluster(
            f"{r.get('event_title','')} {r.get('market_question','')}"
        ):
            continue
        if predicate and not predicate(r):
            continue
        if not is_high_confidence(r):
            continue
        denom += 1
        if is_break(r):
            num += 1
    return {
        "breaks": num,
        "high_confidence_markets": denom,
        "rate": (num / denom) if denom else 0.0,
    }


def relative_risk(snapshot_rows, subset_predicate):
    """
    Break rate of a subset versus its complement, with both rates and the
    ratio. Used for the bracket-vs-everything-else comparison.
    """
    def complement(r):
        return not subset_predicate(r)

    sub = break_rate(snapshot_rows, predicate=subset_predicate)
    rest = break_rate(snapshot_rows, predicate=complement)
    ratio = (sub["rate"] / rest["rate"]) if rest["rate"] else None
    return {"subset": sub, "rest": rest, "relative_risk": ratio}


# ---------------------------------------------------------------------------
# Category and structural breakdowns (on the core sample).
# ---------------------------------------------------------------------------

def by_category(dataset):
    """Per-category break count and exposure, core sample, sorted by exposure."""
    core = core_rows(dataset)
    agg = defaultdict(lambda: {"breaks": 0, "exposure_usd": 0.0})
    for r in core:
        c = r.get("category", "Other")
        agg[c]["breaks"] += 1
        agg[c]["exposure_usd"] += _exposure(r)
    rows = [{"category": c, **v} for c, v in agg.items()]
    rows.sort(key=lambda x: -x["exposure_usd"])
    return rows


def by_bracket_pattern(dataset):
    """
    Break count and exposure split by structural pattern, core sample.
    The two bracket patterns together are the model-failure cohort.
    """
    core = core_rows(dataset)
    agg = defaultdict(lambda: {"breaks": 0, "exposure_usd": 0.0})
    for r in core:
        p = r.get("bracket_pattern", "other")
        agg[p]["breaks"] += 1
        agg[p]["exposure_usd"] += _exposure(r)
    total_n = len(core) or 1
    total_e = sum(_exposure(r) for r in core) or 1.0
    out = []
    for p, v in agg.items():
        out.append({
            "pattern": p,
            "breaks": v["breaks"],
            "breaks_pct": v["breaks"] / total_n,
            "exposure_usd": v["exposure_usd"],
            "exposure_pct": v["exposure_usd"] / total_e,
        })
    out.sort(key=lambda x: -x["exposure_usd"])
    return out


def bracket_concentration(dataset):
    """
    The headline concentration figure: bracket-pattern markets as a share of
    both break count and exposure, core sample.
    """
    rows = by_bracket_pattern(dataset)
    bracket = [r for r in rows if r["pattern"] != "other"]
    return {
        "bracket_breaks": sum(r["breaks"] for r in bracket),
        "bracket_breaks_pct": sum(r["breaks_pct"] for r in bracket),
        "bracket_exposure_usd": sum(r["exposure_usd"] for r in bracket),
        "bracket_exposure_pct": sum(r["exposure_pct"] for r in bracket),
    }


# ---------------------------------------------------------------------------
# Threshold sensitivity and the strict-boundary robustness check.
# ---------------------------------------------------------------------------

def threshold_sensitivity(snapshot_rows, thresholds=(0.90, 0.95, 0.97, 0.99)):
    """
    Break count and exposure at several confidence cuts, on the full sample
    (Iran included, flagged separately by the caller if needed). Demonstrates
    how the sample shrinks as the bar rises.
    """
    from src.utils import to_float as _f

    results = []
    for thr in thresholds:
        floor = 1.0 - thr
        n = exp = iran_n = 0
        for r in snapshot_rows:
            snaps = [_f(r.get(c)) for c in ("snap_7d_pre", "snap_24h_pre", "snap_final")]
            res = r.get("resolution")
            cy = any(v is not None and v > thr for v in snaps)
            cn = any(v is not None and v <= floor for v in snaps)
            broke = (cy and res == "NO") or (cn and res == "YES")
            if not broke:
                continue
            n += 1
            # wrong-side price at this threshold
            if res == "NO":
                price = max((v for v in snaps if v is not None and v > thr), default=None)
            else:
                lo = min((v for v in snaps if v is not None and v <= floor), default=None)
                price = None if lo is None else 1.0 - lo
            vol = _f(r.get("market_volume")) or 0.0
            if price is not None:
                exp += vol * price
        results.append({"threshold": thr, "breaks": n, "exposure_usd": exp})
    return results


def boundary_robustness(snapshot_rows):
    """
    The strict-vs-inclusive boundary check. Reports how many breaks survive
    if the threshold uses strict inequality on both sides (excluding markets
    whose dismissed side sat at exactly the floor). The writeup cites the
    difference as a robustness note.
    """
    from src.utils import to_float as _f, is_iran_cluster

    incl = strict = 0
    for r in snapshot_rows:
        if is_iran_cluster(f"{r.get('event_title','')} {r.get('market_question','')}"):
            continue
        snaps = [_f(r.get(c)) for c in ("snap_7d_pre", "snap_24h_pre", "snap_final")]
        res = r.get("resolution")
        cy = any(v is not None and v > 0.95 for v in snaps)
        cn_incl = any(v is not None and v <= 0.05 for v in snaps)
        cn_strict = any(v is not None and v < 0.05 for v in snaps)
        if (cy and res == "NO") or (cn_incl and res == "YES"):
            incl += 1
        if (cy and res == "NO") or (cn_strict and res == "YES"):
            strict += 1
    return {"inclusive": incl, "strict": strict, "boundary_only": incl - strict}
