"""
Constants, configuration, and small shared transforms.

Everything here is pure and import-only: no network, no file I/O. The
thresholds and conventions defined in this module are the single source
of truth for the rest of the pipeline, so a reviewer can read one file
and know exactly how "high confidence," "a break," and "the sample
window" are defined.
"""

import re
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths. Relative to the repo root, resolved from this file's location so
# the pipeline works regardless of the current working directory.
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "data"
OUTPUT_DIR = REPO_ROOT / "output"

RAW_MARKETS = DATA_DIR / "resolved_markets.csv"          # phase 1 output
SNAPSHOTS = DATA_DIR / "markets_with_snapshots.csv"      # phase 2 output
DATASET = OUTPUT_DIR / "polymarket_breaks_dataset.csv"   # analysis-ready

# ---------------------------------------------------------------------------
# Sample definition. These are the knobs that define the study.
# ---------------------------------------------------------------------------

DATE_FROM = "2024-01-01"
DATE_TO = "2026-05-01"
MIN_EVENT_VOLUME = 10_000

# A market is "high confidence" if the confident side reached this price at
# any snapshot. A "break" is a high-confidence market that resolved against
# that side. The rule is inclusive at the boundary (>= on the confident
# side), matching the published figures; the strict-inequality variant
# (528 markets) is reported as a robustness check in analysis.py.
HIGH_CONFIDENCE = 0.95
BREAK_FLOOR = 0.05  # 1 - HIGH_CONFIDENCE, named to keep the YES/NO branches symmetric

# Snapshot columns, in chronological order.
SNAPSHOT_COLS = ("snap_7d_pre", "snap_24h_pre", "snap_final")

# The Iran cluster: constituent markets resolving on the February 2026
# strike cascade. One underlying event across many contracts, excluded
# from core figures so a single tail event does not dominate cross-category
# numbers. Detection is keyword-based on the event title plus question.
IRAN_KEYWORDS = (
    "iran", "khamenei", "israel military", "israel strike", "yemen",
)

# ---------------------------------------------------------------------------
# Category inference. The Gamma API leaves the category field blank on most
# events, so we infer it from the title when the platform gives nothing.
# Order matters: the first matching bucket wins.
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Category inference. The Gamma API leaves the category field blank on most
# events, so we infer it from the title plus question when the platform
# gives nothing. These are the exact regex rules used to produce the
# published figures: word-boundary patterns, case-insensitive, first
# matching category wins. Priority order matters (Politics before Tech, so
# political-figure markets are not pulled into Tech, etc).
# ---------------------------------------------------------------------------

_RULES = [
    ("Politics", [
        r"\belection", r"\bpresident", r"\bsenate", r"\bcongress",
        r"\bvote\b", r"\bpoll\b", r"\bnominee", r"\bprimary\b",
        r"\bgovernor", r"\bmayor", r"\bcandidate", r"\bparliament",
        r"\bminister\b", r"\bcabinet\b", r"\bspeaker\b",
        r"\bRNC\b", r"\bDNC\b", r"\bGOP\b", r"\bdemocrat", r"\brepublican",
        r"\btrump\b", r"\bbiden\b", r"\bharris\b", r"\bnetanyahu",
        r"\bputin\b", r"\bzelensky", r"\bxi jinping",
    ]),
    ("Crypto", [
        r"\bbitcoin\b", r"\bBTC\b", r"\bethereum\b", r"\bETH\b",
        r"\bSOL\b", r"\bsolana\b", r"\bcrypto", r"\baltcoin",
        r"\bstablecoin", r"\bUSDC\b", r"\bUSDT\b", r"\bDOGE\b",
        r"\bDeFi\b", r"\bNFT\b", r"\bbinance\b", r"\bcoinbase\b",
        r"\b(token|coin) price", r"\bairdrop\b", r"\bmemecoin",
        r"\bXRP\b", r"\bcardano", r"\bADA\b", r"\bAVAX\b", r"\bavalanche",
    ]),
    ("Sports", [
        r"\bNFL\b", r"\bNBA\b", r"\bMLB\b", r"\bNHL\b", r"\bMLS\b",
        r"\bsuper bowl", r"\bworld series", r"\bworld cup", r"\bchampions league",
        r"\bpremier league", r"\bla liga", r"\bbundesliga", r"\bserie A\b",
        r"\bUEFA\b", r"\bFIFA\b", r"\bF1\b", r"\bformula 1\b",
        r"\btennis\b", r"\bgolf\b", r"\bPGA\b", r"\bUFC\b", r"\bMMA\b",
        r"\bolympic", r"\bwimbledon", r"\bgrand slam", r"\bATP\b", r"\bWTA\b",
        r"\bMVP\b", r"\brookie of the year",
        r"\bvs\b.*\b(win|beat|defeat)", r"\bmatch\b", r"\bgame\b",
        r"\bseason\b.*\b(champion|winner)",
    ]),
    ("Macro", [
        r"\bFed\b", r"\bFOMC\b", r"\binterest rate", r"\brate (cut|hike|decision)",
        r"\bCPI\b", r"\binflation\b", r"\bGDP\b", r"\bunemployment",
        r"\bnonfarm payroll", r"\bpayroll", r"\brecession\b", r"\bjobs report",
        r"\bjobless claim", r"\bPPI\b", r"\bPCE\b", r"\btreasury yield",
        r"\bBOJ\b", r"\bECB\b", r"\bBank of (England|Japan|Canada)",
    ]),
    ("Geopolitics", [
        r"\bukraine", r"\brussia\b", r"\bIsrael\b", r"\bgaza\b", r"\bhamas\b",
        r"\biran\b", r"\bnorth korea", r"\bchina\b.*\b(taiwan|invade)",
        r"\bnato\b", r"\bUN\b.*\b(resolution|security)",
        r"\bceasefire", r"\bwar\b", r"\bsanction", r"\btariff",
        r"\btreaty\b", r"\bsummit\b", r"\bpeace deal",
    ]),
    ("Tech", [
        r"\bOpenAI\b", r"\bChatGPT", r"\bGPT-\d", r"\bClaude\b",
        r"\bAnthropic", r"\bgemini\b", r"\bLLama\b", r"\bDeepSeek",
        r"\bAI\b.*\b(launch|release|benchmark)", r"\bIPO\b",
        r"\bElon\b", r"\bMusk\b", r"\bTesla\b", r"\bSpaceX\b",
        r"\bApple\b.*\b(launch|release|iPhone)", r"\bMeta\b.*\b(launch|release)",
        r"\bGoogle\b.*\b(launch|release|product)",
        r"\bAGI\b", r"\bsuperintelligence",
    ]),
    ("Entertainment", [
        r"\bOscar", r"\bgrammy", r"\bemmy\b", r"\bgolden globe",
        r"\bmovie\b", r"\bfilm\b", r"\bbox office", r"\balbum\b",
        r"\bsong\b", r"\bbillboard", r"\bspotify\b", r"\btaylor swift",
        r"\bbeyonce\b", r"\bdrake\b", r"\bkardashian",
        r"\bnetflix\b", r"\bdisney\b", r"\bMCU\b",
    ]),
]

_COMPILED = [
    (cat, [re.compile(p, re.IGNORECASE) for p in patterns])
    for cat, patterns in _RULES
]


def infer_category(text):
    """Return the first category whose patterns match text, else 'Other'."""
    t = text or ""
    for cat, patterns in _COMPILED:
        for pat in patterns:
            if pat.search(t):
                return cat
    return "Other"


def is_iran_cluster(text):
    """True if the market belongs to the excluded Iran cascade."""
    t = (text or "").lower()
    return any(k in t for k in IRAN_KEYWORDS)


def is_crypto_price_bracket(category, text):
    """
    True for crypto markets that discretize a price into range-buckets,
    e.g. "What price will Bitcoin hit in January?" or "Bitcoin above $X".
    These are one half of the model-failure pattern.
    """
    t = (text or "").lower()
    return category == "Crypto" and any(
        k in t for k in ["above $", "price will", "hit in", "settle"]
    )


def is_musk_tweet_bracket(event_title):
    """True for the weekly Elon Musk tweet-count bracket markets."""
    t = (event_title or "").lower()
    return "musk" in t and "tweet" in t


def bracket_pattern(category, event_title, market_question):
    """
    Classify a market's structural pattern. Returns one of:
      'crypto_price_bracket', 'musk_tweet_bracket', or 'other'.
    The first two are the model-failure pattern: a numerical outcome cut
    into mutually exclusive range-buckets traded as independent contracts.
    """
    combined = f"{event_title} {market_question}"
    if is_musk_tweet_bracket(event_title):
        return "musk_tweet_bracket"
    if is_crypto_price_bracket(category, combined):
        return "crypto_price_bracket"
    return "other"


def to_float(value):
    """Parse a value to float, returning None on anything unparseable."""
    if value in (None, "", "None"):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
