"""
The transform step: raw price snapshots -> analysis-ready dataset.

This is the middle of the pipeline that reproducibility usually skips. It
takes the snapshotted markets from data/ and deterministically produces the
one-row-per-break table that every figure in the writeup is built from. If
you delete the committed output/polymarket_breaks_dataset.csv and run this,
you get the same file back, byte for byte.

What this step does, in order:
  1. selection   - keep only markets that "broke" (the in-sample rule)
  2. derivation  - compute break confidence and wrong-side exposure
  3. labelling   - assign category (mechanical), bracket pattern (mechanical),
                   and Iran-cluster membership (mechanical)

Hand-classification by surprise type is NOT done here. That requires human
judgment and lives in a separate, versioned file (output/top40_classifications.csv)
with a status column. Only mechanical labels belong in code.
"""

import csv

from src.utils import (
    SNAPSHOTS, DATASET, OUTPUT_DIR,
    HIGH_CONFIDENCE, BREAK_FLOOR, SNAPSHOT_COLS,
    infer_category, is_iran_cluster, bracket_pattern, to_float,
)

DATASET_FIELDS = [
    "event_id", "event_title", "market_question", "category", "category_source",
    "resolution", "neg_risk", "snap_7d_pre", "snap_24h_pre", "snap_final",
    "break_confidence", "market_volume_usd", "wrong_side_exposure_usd",
    "end_date", "bracket_pattern", "in_iran_cluster",
]


def _snapshots(row):
    """The three snapshot prices as floats, in chronological order."""
    return [to_float(row.get(c)) for c in SNAPSHOT_COLS]


def is_high_confidence(row):
    """
    True if the confident side reached the threshold at any snapshot.
    Inclusive at the boundary: YES >= HIGH_CONFIDENCE counts as a confident
    YES side; YES <= BREAK_FLOOR counts as a confident NO side.
    """
    snaps = _snapshots(row)
    conf_yes = any(v is not None and v > HIGH_CONFIDENCE for v in snaps)
    conf_no = any(v is not None and v <= BREAK_FLOOR for v in snaps)
    return conf_yes or conf_no


def is_break(row):
    """
    A high-confidence market that resolved against the confident side.
      confident YES (price > 0.95) but resolved NO  -> break
      confident NO  (price <= 0.05) but resolved YES -> break
    """
    snaps = _snapshots(row)
    res = row.get("resolution")
    conf_yes = any(v is not None and v > HIGH_CONFIDENCE for v in snaps)
    conf_no = any(v is not None and v <= BREAK_FLOOR for v in snaps)
    return (conf_yes and res == "NO") or (conf_no and res == "YES")


def break_confidence(row):
    """
    The confident-side price at the break, i.e. how sure the market was of
    the wrong answer. For a NO resolution it is the highest YES price seen;
    for a YES resolution it is one minus the lowest YES price seen. Returns
    a value in (0.95, 1.0] for a genuine break, or None.
    """
    snaps = [v for v in _snapshots(row) if v is not None]
    if not snaps:
        return None
    res = row.get("resolution")
    if res == "NO":
        hi = max(v for v in snaps if v > HIGH_CONFIDENCE) if any(
            v > HIGH_CONFIDENCE for v in snaps) else None
        return hi
    if res == "YES":
        lo = min(v for v in snaps if v <= BREAK_FLOOR) if any(
            v <= BREAK_FLOOR for v in snaps) else None
        return None if lo is None else 1.0 - lo
    return None


def wrong_side_exposure(row):
    """
    Upper-bound dollar exposure on the wrong side of a break:

        exposure = market_volume * loss_per_share

    where loss_per_share is the confident-side price (a NO-resolved market
    priced at 0.97 YES loses 0.97 per wrong YES share) or one minus it for
    a YES resolution.

    THIS IS AN UPPER BOUND, NOT REALIZED LOSS. market_volume counts both
    sides of the book and earlier trades at lower confidence, so true trader
    losses are smaller. The writeup labels it as a bound everywhere it
    appears; do not present it as money actually lost.
    """
    conf = break_confidence(row)
    if conf is None:
        return 0.0
    vol = to_float(row.get("market_volume")) or 0.0
    # break_confidence already returns the wrong-side price for both the
    # YES and NO branches, so it is the loss per wrong share directly.
    return vol * conf


def build_dataset(write=True):
    """
    Read the cached snapshots, apply the selection rule, compute derived
    columns and mechanical labels, and return the analysis-ready rows.

    If write=True, also writes output/polymarket_breaks_dataset.csv. The
    file is a committed convenience; this function is its source of truth.
    """
    src_rows = list(csv.DictReader(open(SNAPSHOTS, encoding="utf-8")))
    out = []
    for r in src_rows:
        if not is_break(r):
            continue
        title, question = r.get("event_title", ""), r.get("market_question", "")
        combined = f"{title} {question}"

        platform_cat = (r.get("category") or "").strip()
        category = platform_cat if platform_cat else infer_category(combined)
        cat_source = "platform" if platform_cat else "inferred"

        conf = break_confidence(r)
        snaps = _snapshots(r)
        out.append({
            "event_id": r.get("event_id", ""),
            "event_title": title,
            "market_question": question,
            "category": category,
            "category_source": cat_source,
            "resolution": r.get("resolution", ""),
            "neg_risk": r.get("neg_risk", ""),
            "snap_7d_pre": "" if snaps[0] is None else f"{snaps[0]:.4f}",
            "snap_24h_pre": "" if snaps[1] is None else f"{snaps[1]:.4f}",
            "snap_final": "" if snaps[2] is None else f"{snaps[2]:.4f}",
            "break_confidence": "" if conf is None else f"{conf:.4f}",
            "market_volume_usd": f"{(to_float(r.get('market_volume')) or 0):.2f}",
            "wrong_side_exposure_usd": f"{wrong_side_exposure(r):.2f}",
            "end_date": (r.get("end_date") or "")[:10],
            "bracket_pattern": bracket_pattern(category, title, question),
            "in_iran_cluster": "true" if is_iran_cluster(combined) else "false",
        })

    if write:
        OUTPUT_DIR.mkdir(exist_ok=True)
        with open(DATASET, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=DATASET_FIELDS)
            writer.writeheader()
            writer.writerows(out)
    return out
