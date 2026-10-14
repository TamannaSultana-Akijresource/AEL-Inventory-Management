"""Headless daily generator for the AEL dashboard (open code edition).

Pipeline:  read DWH -> build a self-contained index.html -> push to GitHub.

Usage
-----
    python generate_dashboard.py                 # real data, then push
    python generate_dashboard.py --no-push       # real data, stay local
    python generate_dashboard.py --demo          # synthetic data (no DB), local
    python generate_dashboard.py --demo --push   # synthetic data, then push
    python generate_dashboard.py --date 2026-10-14   # pin the "today"
    python generate_dashboard.py --open          # open the report when done

The daily button ``run_daily.bat`` calls this with ``--push``.
"""

from __future__ import annotations

import argparse
import shutil
import sys
import traceback
from datetime import date, datetime
from zoneinfo import ZoneInfo

import config as C
import dashboard
import db
import gateway_source
import github_publish
from queries import DETAIL_SQL, SUMMARY_SQL


try:  # make console output safe on Windows code pages
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def log(msg: str) -> None:
    line = f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}"
    print(line, flush=True)
    try:
        C.LOG_DIR.mkdir(exist_ok=True)
        with open(C.LOG_DIR / f"run_{datetime.now():%Y-%m}.log", "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Data sources
# ---------------------------------------------------------------------------
def load_live(start: str, end: str, source: str = "gateway"):
    if source == "sql":
        log(f"Querying DWH directly (pyodbc) for window {start} -> {end} ...")
        raw_summary = db.run_query(SUMMARY_SQL, {"start": start, "end": end})
        raw_detail = db.run_query(DETAIL_SQL, {"start": start, "end": end})
    else:
        log(f"Querying DWH via the enterprise API gateway for window {start} -> {end} ...")
        raw_summary, raw_detail = gateway_source.load_live(start, end)
    summary = dashboard.prepare_summary(raw_summary)
    detail = dashboard.prepare_detail(raw_detail)
    log(f"Loaded {len(summary):,} summary lines and {len(detail):,} order lines.")
    return summary, detail


def load_demo(start: str, end: str):
    """Deterministic synthetic data so the pipeline can be exercised offline."""
    log("DEMO mode: generating synthetic data (no database connection).")
    import random
    rng = random.Random(20261014)
    items = [
        "AEL Flour - 2kg Pack", "AEL Flour - 1kg Pack", "AEL Soyabean Oil - 5L",
        "AEL Soyabean Oil - 2L", "AEL Soyabean Oil - 1L", "AEL Salt - 1kg",
        "AEL Sugar - 1kg", "AEL Lentil - 1kg", "AEL Rice - 25kg", "AEL Rice - 50kg",
        "AEL Spice Mix - 200g", "AEL Tejgoan Tea - 400g",
    ]
    ships = C.AEL_SHIPPOINTS
    import pandas as pd

    srows, drows = [], []
    for ship in ships:
        for item in items:
            order = rng.randint(200, 6000)
            sales = int(order * rng.uniform(0.55, 1.0))
            variance = order - sales
            stock = rng.choice([-1, rng.randint(0, 8000), rng.randint(0, 8000)])
            if stock < 0:
                stock = -rng.randint(20, 400)
            diff = stock - variance
            srows.append({
                "Shippoint Name": ship, "Item Name": item,
                "Sum of Order Quantity (Bag)": order,
                "Sum of Sales Quantity (Bag)": sales,
                "Sum of Variance in Order Quantity (Bag)": variance,
                "Order Value": order * rng.uniform(45, 320),
                "Stock": stock, "Diff.": diff,
            })
            for k in range(rng.randint(3, 9)):
                oq = rng.randint(20, 400)
                sq = int(oq * rng.uniform(0.3, 1.0))
                vq = oq - sq
                mt = oq * rng.uniform(0.001, 0.05)
                drows.append({
                    "SO Date": (datetime(2026, 10, rng.randint(1, 14))),
                    "SO Code": f"SO{rng.randint(260000, 269999)}",
                    "Channel Name": rng.choice(["B2B", "Distribution", "Modern Trade", "Export"]),
                    "Shippoint Name": ship, "Customer Name": rng.choice(
                        ["Rahim Traders", "Karim Store", "Bashundhara Mart", "Agro Feed Ltd",
                         "Meghna Distributors", "Nabin Enterprise", "City Super Shop"]),
                    "Item Name": item,
                    "Order Quantity (Bag)": oq, "Order Quantity (MT)": mt,
                    "Total Order Value": oq * rng.uniform(45, 320),
                    "Sales Quantity (Bag)": sq, "Sales Quantity (MT)": mt * sq / max(oq, 1),
                    "Total Sales Value": sq * rng.uniform(45, 320),
                    "Variance in Order Quantity (Bag)": vq,
                    "Variance in Order Quantity (MT)": mt * vq / max(oq, 1),
                    "Total Variance in Order Value": vq * rng.uniform(45, 320),
                    "OTIF": round(sq / max(oq, 1), 4),
                })
    summary = dashboard.prepare_summary(pd.DataFrame(srows))
    detail = dashboard.prepare_detail(pd.DataFrame(drows))
    log(f"DEMO loaded {len(summary):,} summary lines and {len(detail):,} order lines.")
    return summary, detail


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------
def write_outputs(html_text: str, generated_at: datetime) -> tuple[str, str]:
    C.HERE.mkdir(exist_ok=True)
    index_path = C.INDEX_FILE
    index_path.write_text(html_text, encoding="utf-8")

    day_dir = C.EXPORT_DIR / generated_at.strftime("%Y-%m-%d")
    day_dir.mkdir(parents=True, exist_ok=True)
    archive = day_dir / f"AEL_MTD_Dashboard_{generated_at:%Y-%m-%d_%H-%M-%S}.html"
    shutil.copy2(index_path, archive)
    return str(index_path), str(archive)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Generate and publish the AEL dashboard.")
    ap.add_argument("--demo", action="store_true", help="use synthetic data (offline)")
    ap.add_argument("--source", choices=["gateway", "sql"], default="gateway",
                    help="live data path: MCP gateway (default) or direct SQL")
    ap.add_argument("--push", action="store_true", help="push index.html to GitHub")
    ap.add_argument("--date", help="treat this ISO date as 'today' (default: now in Dhaka)")
    ap.add_argument("--open", action="store_true", help="open the report in a browser")
    args = ap.parse_args(argv)

    tz = ZoneInfo(C.TZ_NAME)
    today = date.fromisoformat(args.date) if args.date else datetime.now(tz).date()
    start, end = dashboard.month_bounds(today)
    mode = "DEMO" if args.demo else f"LIVE/{args.source}"
    log(f"=== AEL dashboard run ({mode}) window {start} -> {end} ===")

    try:
        if args.demo:
            summary, detail = load_demo(start, end)
            fallback = False
        else:
            summary, detail = load_live(start, end, args.source)
            fallback = False
    except Exception as exc:  # noqa: BLE001
        log(f"Live data load failed: {exc}")
        if args.demo:
            return 2
        log("Falling back to DEMO data so a dashboard is still produced locally.")
        log("The DEMO dashboard will NOT be pushed to GitHub - fix credentials, then re-run.")
        summary, detail = load_demo(start, end)
        args.demo = True
        fallback = True

    if summary is None or summary.empty:
        log("No rows returned for the current window. Nothing written.")
        return 3

    generated_at = datetime.now(tz)
    html_text = dashboard.build_html(summary, detail, generated_at, start,
                                     today.isoformat(), demo=args.demo)
    index_path, archive = write_outputs(html_text, generated_at)
    log(f"Wrote {index_path}")
    log(f"Archived {archive}")

    if args.open:
        try:
            import webbrowser
            webbrowser.open(index_path)
        except Exception:
            pass

    if args.push and fallback:
        log("Skipping GitHub push: only DEMO data is available this run.")
        return 5

    if args.push:
        log("Publishing to GitHub ...")
        github_publish.ensure_repo(C.HERE)
        ok, msg = github_publish.publish(
            C.HERE, [C.PUBLISH_FILE],
            f"Update AEL dashboard {generated_at:%Y-%m-%d %H:%M:%S}",
        )
        (log if ok else log)("Push: " + msg)
        if not ok:
            return 4
    else:
        log("Skipping GitHub push (use --push to publish).")

    log("=== done ===")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception:  # noqa: BLE001
        traceback.print_exc()
        raise SystemExit(1)
