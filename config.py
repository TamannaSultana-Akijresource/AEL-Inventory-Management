"""Central configuration for the AEL dashboard (open code edition).

Everything tunable lives here so the rest of the code stays clean.
"""

from __future__ import annotations

import os
from pathlib import Path

# --------------------------------------------------------------------------
# Paths
# --------------------------------------------------------------------------
HERE = Path(__file__).resolve().parent
EXPORT_DIR = HERE / "html_exports"          # timestamped archive of every run
INDEX_FILE = HERE / "index.html"            # the published dashboard
LOG_DIR = HERE / "logs"

# --------------------------------------------------------------------------
# Scope
# --------------------------------------------------------------------------
BU = 144  # Akij Essentials Ltd.

AEL_SHIPPOINTS: list[str] = [
    "AEL Boardbazar Gazipur",
    "AEL CONSUMER CTG",
    "AEL Consumer Depot Barisal",
    "AEL Faridpur",
    "AEL Narayanganj-Consumer",
    "North Bengal DC",
    "TVS",  # AEL Tejgoan
]

TITLE = "AEL - MTD Order Fulfilment & Stock Coverage"
TZ_NAME = "Asia/Dhaka"

# --------------------------------------------------------------------------
# Business rules
# --------------------------------------------------------------------------
SAFE_BUFFER = 50           # bags of cover considered "Safe" above this
STATUS_ORDER = ["Risk", "Check Again", "Pay Attention", "Safe"]

# --------------------------------------------------------------------------
# Theme
# --------------------------------------------------------------------------
INK = "#1b232c"
MUTED = "#63707e"
LINE = "#e2e6ea"
PANEL = "#ffffff"
CANVAS = "#f6f7f9"
ACCENT = "#2d6a68"

RISK_FG, RISK_BG = "#a5231b", "#fbeceb"
WATCH_FG, WATCH_BG = "#9a5b06", "#fdf4e6"
SAFE_FG, SAFE_BG = "#14663f", "#eaf4ee"
DATA_FG, DATA_BG = "#54606e", "#eceef1"

STATUS_COLOR = {
    "Risk": RISK_FG, "Pay Attention": WATCH_FG,
    "Safe": SAFE_FG, "Check Again": DATA_FG,
}
STATUS_BG = {
    "Risk": RISK_BG, "Pay Attention": WATCH_BG,
    "Safe": SAFE_BG, "Check Again": DATA_BG,
}

# --------------------------------------------------------------------------
# GitHub publishing
# --------------------------------------------------------------------------
GITHUB_REPO = "https://github.com/TamannaSultana-Akijresource/AEL-Inventory-Management.git"
GITHUB_BRANCH = os.environ.get("AEL_GITHUB_BRANCH", "main")
PUBLISH_FILE = "index.html"     # the file GitHub Pages serves

# --------------------------------------------------------------------------
# Misc
# --------------------------------------------------------------------------
CACHE_TTL = 300  # seconds (Streamlit app only)
