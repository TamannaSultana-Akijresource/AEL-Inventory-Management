"""AEL - MTD Order Fulfilment & Stock Coverage (open code edition).

Interactive Streamlit dashboard with manual editing and one-click publish.
For the automated daily report + GitHub push, use ``run_daily.bat``
(``generate_dashboard.py``) instead.

Run locally:   streamlit run app.py
"""

from __future__ import annotations

import difflib
import os
from datetime import datetime
from zoneinfo import ZoneInfo

import altair as alt
import pandas as pd
import streamlit as st

import config as C
import dashboard
import github_publish
from db import config_is_complete, get_config, heartbeat, run_query
from queries import DETAIL_SQL, SUMMARY_SQL

TZ = ZoneInfo(C.TZ_NAME)

st.set_page_config(
    page_title="AEL - MTD Order Fulfilment & Stock Coverage",
    page_icon=None,
    layout="wide",
    initial_sidebar_state="expanded",
)


# ---------------------------------------------------------------------------
# Styling
# ---------------------------------------------------------------------------
def inject_css() -> None:
    st.markdown(
        f"""
        <style>
        .stApp {{ background: {C.CANVAS}; }}
        html, body, [class*="css"] {{
            font-family: "Inter", "Segoe UI", system-ui, -apple-system, sans-serif;
            color: {C.INK};
        }}
        .block-container {{ padding-top: 1.6rem; padding-bottom: 3rem; max-width: 1500px; }}
        #MainMenu, footer {{ visibility: hidden; }}
        .hdr {{ display: flex; justify-content: space-between; align-items: flex-end;
            border-bottom: 2px solid {C.INK}; padding-bottom: .8rem; margin-bottom: 1.4rem; }}
        .hdr h1 {{ font-size: 1.55rem; font-weight: 650; letter-spacing: -.02em; margin: 0; color: {C.INK}; }}
        .hdr .sub {{ font-size: .82rem; color: {C.MUTED}; margin-top: .25rem; }}
        .hdr .clock {{ text-align: right; font-size: .78rem; color: {C.MUTED}; line-height: 1.55; }}
        .hdr .clock b {{ color: {C.INK}; font-weight: 600; }}
        .kpi {{ background: {C.PANEL}; border: 1px solid {C.LINE}; border-radius: 4px;
            padding: .9rem 1rem .95rem; height: 100%; border-top: 3px solid {C.ACCENT}; }}
        .kpi .lab {{ font-size: .68rem; text-transform: uppercase; letter-spacing: .07em;
            color: {C.MUTED}; font-weight: 600; }}
        .kpi .val {{ font-size: 1.5rem; font-weight: 650; letter-spacing: -.02em;
            margin-top: .3rem; line-height: 1.1; }}
        .kpi .note {{ font-size: .74rem; color: {C.MUTED}; margin-top: .3rem; }}
        .kpi.risk {{ border-top-color: {C.RISK_FG}; }}
        .kpi.watch {{ border-top-color: {C.WATCH_FG}; }}
        .kpi.safe {{ border-top-color: {C.SAFE_FG}; }}
        .kpi.data {{ border-top-color: {C.DATA_FG}; }}
        .sect {{ font-size: .72rem; text-transform: uppercase; letter-spacing: .09em;
            font-weight: 700; color: {C.MUTED}; margin: 1.8rem 0 .55rem;
            border-bottom: 1px solid {C.LINE}; padding-bottom: .4rem; }}
        .pill {{ display: inline-block; padding: .12rem .5rem; border-radius: 3px;
            font-size: .72rem; font-weight: 600; margin-right: .35rem; }}
        .scope {{ display: inline-block; padding: .1rem .55rem; border-radius: 3px;
            font-size: .72rem; font-weight: 600; margin: .1rem .35rem .1rem 0;
            background: {C.PANEL}; border: 1px solid {C.LINE}; color: {C.INK}; }}
        .stButton>button {{ border-radius: 3px; border: 1px solid {C.INK}; background: {C.INK};
            color: #fff; font-weight: 600; font-size: .82rem; padding: .42rem 1rem; }}
        .stButton>button:hover {{ background: {C.ACCENT}; border-color: {C.ACCENT}; color: #fff; }}
        section[data-testid="stSidebar"] {{ background: {C.PANEL}; border-right: 1px solid {C.LINE}; }}
        .foot {{ font-size: .74rem; color: {C.MUTED}; border-top: 1px solid {C.LINE};
                 padding-top: .8rem; margin-top: 2.2rem; line-height: 1.7; }}
        </style>
        """,
        unsafe_allow_html=True,
    )


# ---------------------------------------------------------------------------
# Data access
# ---------------------------------------------------------------------------
@st.cache_data(ttl=C.CACHE_TTL, show_spinner=False)
def load_summary(start: str, end: str, _bust: int = 0) -> pd.DataFrame:
    return dashboard.prepare_summary(run_query(SUMMARY_SQL, {"start": start, "end": end}))


@st.cache_data(ttl=C.CACHE_TTL, show_spinner=False)
def load_detail(start: str, end: str, _bust: int = 0) -> pd.DataFrame:
    return dashboard.prepare_detail(run_query(DETAIL_SQL, {"start": start, "end": end}))


# ---------------------------------------------------------------------------
# Spelling-tolerant search
# ---------------------------------------------------------------------------
def _norm(s: str) -> str:
    return "".join(ch for ch in str(s).lower() if ch.isalnum() or ch == " ").strip()


def fuzzy_score(option: str, query: str) -> float:
    o, q = _norm(option), _norm(query)
    if not q:
        return 1.0
    if q in o:
        return 1.0
    best = difflib.SequenceMatcher(None, q, o).ratio()
    for word in o.split():
        best = max(best, difflib.SequenceMatcher(None, q, word).ratio())
    q_words = q.split()
    if len(q_words) > 1:
        per = [max((difflib.SequenceMatcher(None, w, ow).ratio() for ow in o.split()),
                   default=0.0) for w in q_words]
        best = max(best, sum(per) / len(per))
    return best


def fuzzy_filter(options: list[str], query: str, cutoff: float = 0.62) -> list[str]:
    if not query.strip():
        return options
    scored = [(o, fuzzy_score(o, query)) for o in options]
    hits = [o for o, s in scored if s >= cutoff]
    if hits:
        return sorted(hits, key=lambda o: -dict(scored)[o])
    hits = [o for o, s in scored if s >= 0.45]
    return sorted(hits, key=lambda o: -dict(scored)[o])[:40]


# ---------------------------------------------------------------------------
# UI helpers
# ---------------------------------------------------------------------------
def kpi(col, label: str, value: str, note: str = "", tone: str = "") -> None:
    col.markdown(
        f"""<div class="kpi {tone}"><div class="lab">{label}</div>
            <div class="val">{value}</div><div class="note">{note}</div></div>""",
        unsafe_allow_html=True,
    )


def bar_chart(df: pd.DataFrame, x: str, y: str, height: int = 260):
    return (
        alt.Chart(df)
        .mark_bar(size=15, color=C.ACCENT, cornerRadiusEnd=1)
        .encode(
            x=alt.X(f"{x}:Q", title=None,
                    axis=alt.Axis(grid=True, gridColor=C.LINE, format="~s", labelColor=C.MUTED)),
            y=alt.Y(f"{y}:N", sort="-x", title=None,
                    axis=alt.Axis(labelColor=C.INK, labelLimit=210, labelFontSize=11)),
            tooltip=[alt.Tooltip(f"{y}:N"), alt.Tooltip(f"{x}:Q", format=",.0f")],
        )
        .properties(height=height)
        .configure_view(strokeWidth=0)
        .configure_axis(domainColor=C.LINE, tickColor=C.LINE)
    )


def multi_filter(label: str, options: list[str], key: str) -> list[str]:
    st.sidebar.markdown(f"**{label}**")
    c1, c2 = st.sidebar.columns(2)
    if c1.button("All", key=f"{key}_all", width="stretch"):
        st.session_state[key] = list(options)
    if c2.button("Clear", key=f"{key}_clear", width="stretch"):
        st.session_state[key] = []
    picked = st.sidebar.multiselect(label, options, key=key, label_visibility="collapsed",
                                    placeholder=f"All ({len(options)})")
    return picked or list(options)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> None:
    inject_css()
    st.session_state.setdefault("bust", 0)
    st.session_state.setdefault("last_refresh", datetime.now(TZ))

    cfg = get_config()
    if not config_is_complete(cfg):
        st.error(
            "Database credentials are not configured. Add an **[mssql]** section to "
            "`.streamlit/secrets.toml`, or set DWH_* environment variables."
        )
        st.stop()

    now = datetime.now(TZ)
    start, end = dashboard.month_bounds(now.date())

    st.markdown(
        f"""
        <div class="hdr">
          <div><h1>AEL - MTD Order Fulfilment &amp; Stock Coverage</h1>
            <div class="sub">Month to date &middot; {now.strftime('%d %B %Y')} &middot;
                 {len(C.AEL_SHIPPOINTS)} ship points &middot; sales orders against live warehouse stock</div></div>
          <div class="clock">
            <div>Dhaka time &nbsp;<b>{now.strftime('%d %b %Y, %I:%M %p')}</b></div>
            <div>Last refresh &nbsp;<b>{st.session_state.last_refresh.strftime('%I:%M:%S %p')}</b></div>
          </div>
        </div>""",
        unsafe_allow_html=True,
    )
    st.markdown(
        "".join(f'<span class="scope">{s}</span>' for s in C.AEL_SHIPPOINTS)
        + f'<span class="scope" style="color:{C.MUTED}">AEL Tejgoan = TVS in source</span>',
        unsafe_allow_html=True,
    )

    st.sidebar.markdown("### Controls")
    if st.sidebar.button("Refresh data", width="stretch"):
        st.cache_data.clear()
        st.session_state.bust += 1
        st.session_state.last_refresh = datetime.now(TZ)
        st.rerun()

    srv = heartbeat()
    st.sidebar.caption(
        f"Connected - {cfg['host']} / {cfg['database']}"
        + (f"\n\nServer clock: {srv:%d %b %Y %H:%M}" if srv is not None else "")
    )
    st.sidebar.divider()

    try:
        with st.spinner("Querying DWH..."):
            summary = load_summary(start, end, st.session_state.bust)
            detail = load_detail(start, end, st.session_state.bust)
    except Exception as exc:  # noqa: BLE001
        st.error(f"Query failed: {exc}")
        st.stop()

    if summary.empty:
        st.warning("No sales orders recorded for these ship points this month yet.")
        st.stop()

    st.sidebar.markdown("### Search")
    search = st.sidebar.text_input("Search", placeholder="Ship point, item, customer...",
                                   label_visibility="collapsed")
    if search.strip():
        st.sidebar.caption("Spelling-tolerant - near matches are included.")

    all_ships = sorted(summary["Shippoint Name"].unique().tolist())
    all_items = sorted(summary["Item Name"].unique().tolist())
    if search.strip():
        ship_opts = fuzzy_filter(all_ships, search)
        item_opts = fuzzy_filter(all_items, search)
        if ship_opts and not item_opts:
            item_opts = all_items
        elif item_opts and not ship_opts:
            ship_opts = all_ships
    else:
        ship_opts, item_opts = all_ships, all_items

    st.sidebar.divider()
    sel_ships = multi_filter("Ship point", ship_opts, "f_ship")
    st.sidebar.divider()
    sel_items = multi_filter("Item", item_opts, "f_item")
    st.sidebar.divider()
    sel_status = st.sidebar.multiselect("Status", C.STATUS_ORDER, default=C.STATUS_ORDER,
                                        placeholder="All") or C.STATUS_ORDER

    sdf = summary[
        summary["Shippoint Name"].isin(sel_ships)
        & summary["Item Name"].isin(sel_items)
        & summary["Status"].isin(sel_status)
    ].copy()
    ddf = detail[
        detail["Shippoint Name"].isin(sel_ships) & detail["Item Name"].isin(sel_items)
    ].copy()
    if search.strip():
        cust_hits = fuzzy_filter(sorted(detail["Customer Name"].unique().tolist()), search)
        mask = (
            ddf["Shippoint Name"].isin(fuzzy_filter(all_ships, search))
            | ddf["Item Name"].isin(fuzzy_filter(all_items, search))
            | ddf["Customer Name"].isin(cust_hits)
        )
        if mask.any():
            ddf = ddf[mask]

    if sdf.empty:
        st.warning("No rows match the current filters.")
        st.stop()

    order_qty = sdf["Sum of Order Quantity (Bag)"].sum()
    sales_qty = sdf["Sum of Sales Quantity (Bag)"].sum()
    var_qty = sdf["Sum of Variance in Order Quantity (Bag)"].sum()
    stock_qty = sdf["Stock"].sum()
    fill = (sales_qty / order_qty * 100) if order_qty else 0.0
    counts = sdf["Status"].value_counts()
    n_risk = int(counts.get("Risk", 0))
    n_watch = int(counts.get("Pay Attention", 0))
    n_safe = int(counts.get("Safe", 0))
    n_data = int(counts.get("Check Again", 0))
    risk_gap = abs(sdf.loc[sdf["Status"] == "Risk", "Diff."].sum())

    c = st.columns(4)
    kpi(c[0], "Order quantity", f"{order_qty:,.0f}", f"{sdf['Order Value'].sum()/1e6:,.1f} M order value - bag")
    kpi(c[1], "Sales quantity", f"{sales_qty:,.0f}", f"Fill rate {fill:,.1f}% of ordered")
    kpi(c[2], "Open variance", f"{var_qty:,.0f}", "Ordered but not yet delivered - bag")
    kpi(c[3], "Stock on hand", f"{stock_qty:,.0f}", f"{len(sdf):,} ship point x item lines")
    c = st.columns(5)
    kpi(c[0], "At risk", f"{n_risk:,}", f"Short by {risk_gap:,.0f} bag in total", "risk")
    kpi(c[1], "Check data", f"{n_data:,}", "Ledger shows negative stock - verify", "data")
    kpi(c[2], "Pay attention", f"{n_watch:,}", f"Cover between 0 and {C.SAFE_BUFFER} bag", "watch")
    kpi(c[3], "Safe", f"{n_safe:,}", f"Cover above {C.SAFE_BUFFER} bag", "safe")
    kpi(c[4], "Ship points live", f"{sdf['Shippoint Name'].nunique():,}", f"{sdf['Item Name'].nunique():,} distinct items")

    st.markdown('<div class="sect">Where the exposure sits</div>', unsafe_allow_html=True)
    g1, g2 = st.columns([1.15, 1])
    with g1:
        top_risk = (sdf[sdf["Status"] == "Risk"].assign(Shortfall=lambda d: d["Diff."].abs())
                    .nlargest(10, "Shortfall")[["Shippoint Name", "Item Name", "Shortfall"]])
        if top_risk.empty:
            st.caption("No confirmed shortfalls in the current selection.")
        else:
            top_risk["Line"] = top_risk["Item Name"] + "  -  " + top_risk["Shippoint Name"]
            st.caption("Largest confirmed shortfalls (bag) - excludes Check Again lines")
            st.altair_chart(bar_chart(top_risk, "Shortfall", "Line", height=290), width="stretch")
    with g2:
        by_ship = (sdf.groupby("Shippoint Name", as_index=False)
                   .agg(Variance=("Sum of Variance in Order Quantity (Bag)", "sum"))
                   .nlargest(10, "Variance"))
        st.caption("Open variance by ship point (bag)")
        st.altair_chart(bar_chart(by_ship, "Variance", "Shippoint Name", height=290), width="stretch")

    st.markdown('<div class="sect">Ship point x item - coverage against open variance</div>',
                unsafe_allow_html=True)
    st.markdown(
        f"""<div style="margin-bottom:.6rem">
          <span class="pill" style="background:{C.RISK_BG};color:{C.RISK_FG}">Risk - Diff &lt; 0</span>
          <span class="pill" style="background:{C.WATCH_BG};color:{C.WATCH_FG}">Pay Attention - 0 to {C.SAFE_BUFFER}</span>
          <span class="pill" style="background:{C.SAFE_BG};color:{C.SAFE_FG}">Safe - &gt; {C.SAFE_BUFFER}</span>
          <span class="pill" style="background:{C.DATA_BG};color:{C.DATA_FG}">Check Again - Stock &lt; 0</span>
        </div>""",
        unsafe_allow_html=True,
    )

    cols = ["Shippoint Name", "Item Name", "Sum of Order Quantity (Bag)",
            "Sum of Sales Quantity (Bag)", "Sum of Variance in Order Quantity (Bag)",
            "Stock", "Diff.", "Status", "Remarks"]
    view = sdf[cols].sort_values(
        ["Status", "Diff."],
        key=lambda s: s.map({v: i for i, v in enumerate(C.STATUS_ORDER)}) if s.name == "Status" else s,
    ).reset_index(drop=True)

    st.caption("Manual editing is enabled. Edits affect only this session and the generated HTML; the database is never changed.")
    edited_summary = st.data_editor(
        view, width="stretch", height=460, hide_index=True, key="editable_summary", num_rows="fixed",
        column_config={
            "Shippoint Name": st.column_config.TextColumn("Shippoint Name", pinned=True),
            "Item Name": st.column_config.TextColumn("Item Name", pinned=True),
            "Sum of Order Quantity (Bag)": st.column_config.NumberColumn("Order Qty (Bag)"),
            "Sum of Sales Quantity (Bag)": st.column_config.NumberColumn("Sales Qty (Bag)"),
            "Sum of Variance in Order Quantity (Bag)": st.column_config.NumberColumn("Variance (Bag)"),
            "Stock": st.column_config.NumberColumn("Stock"),
            "Diff.": st.column_config.NumberColumn("Diff."),
            "Status": st.column_config.SelectboxColumn("Status", options=C.STATUS_ORDER, required=False),
            "Remarks": st.column_config.TextColumn("Remarks", width="large"),
        },
    )
    st.download_button("Download this table (CSV)",
                       edited_summary.to_csv(index=False).encode("utf-8"),
                       file_name=f"ael_mtd_coverage_{now:%Y-%m-%d}.csv", mime="text/csv")

    st.markdown(f'<div class="sect">Sales order history - {now:%B %Y} month to date ({len(ddf):,} lines)</div>',
                unsafe_allow_html=True)
    dcols = ["SL", "SO Date", "SO Code", "Channel Name", "Shippoint Name", "Customer Name",
             "Item Name", "Order Quantity (Bag)", "Order Quantity (MT)", "Total Order Value",
             "Sales Quantity (Bag)", "Sales Quantity (MT)", "Total Sales Value",
             "Variance in Order Quantity (Bag)", "Variance in Order Quantity (MT)",
             "Total Variance in Order Value", "OTIF"]
    edited_detail = st.data_editor(
        ddf[dcols], width="stretch", height=430, hide_index=True, key="editable_detail", num_rows="fixed",
        column_config={
            "SO Date": st.column_config.DateColumn(format="DD MMM YYYY"),
            "OTIF": st.column_config.NumberColumn("OTIF", min_value=0.0, max_value=1.0, step=0.01),
        },
    )
    st.download_button("Download order history (CSV)",
                       edited_detail.to_csv(index=False).encode("utf-8"),
                       file_name=f"ael_sales_order_history_{now:%Y-%m-%d}.csv", mime="text/csv")

    st.markdown('<div class="sect">Report export</div>', unsafe_allow_html=True)
    e1, e2 = st.columns(2)
    with e1:
        if st.button("Generate HTML snapshot", width="stretch"):
            gen = datetime.now(TZ)
            html_text = dashboard.build_html(edited_summary, edited_detail, gen, start,
                                             now.date().isoformat())
            day_dir = C.EXPORT_DIR / f"{gen:%Y-%m-%d}"
            day_dir.mkdir(parents=True, exist_ok=True)
            path = day_dir / f"AEL_MTD_Dashboard_{gen:%Y-%m-%d_%H-%M-%S}.html"
            path.write_text(html_text, encoding="utf-8")
            C.INDEX_FILE.write_text(html_text, encoding="utf-8")
            st.session_state["latest_html_path"] = str(path)
            st.session_state["latest_html_text"] = html_text
            st.success(f"HTML generated and copied to index.html: {path.name}")
    with e2:
        if st.button("Publish index.html to GitHub", width="stretch"):
            if not C.INDEX_FILE.exists():
                st.error("Generate the HTML snapshot first.")
            else:
                github_publish.ensure_repo(C.HERE)
                ok, msg = github_publish.publish(
                    C.HERE, [C.PUBLISH_FILE],
                    f"Update AEL dashboard {datetime.now(TZ):%Y-%m-%d %H:%M:%S}")
                (st.success if ok else st.error)(msg)

    if st.session_state.get("latest_html_text"):
        st.download_button("Download latest generated HTML",
                           st.session_state["latest_html_text"].encode("utf-8"),
                           file_name="index.html", mime="text/html")

    st.markdown(
        f"""<div class="foot">
        Scope - {len(C.AEL_SHIPPOINTS)} AEL ship points. "AEL Tejgoan" is recorded in the source
        system under ship point code "TVS"; the two are merged here.<br>
        Stock is the running sum of every inventory transaction on record for the warehouse(s)
        mapped to the ship point. Where a warehouse log has no opening-balance entry the sum can
        go negative even though physical stock cannot - those lines are marked <b>Check Again</b>.<br>
        Source - DWH: oms.tblSalesOrderHeaderArc + oms.tblSalesOrderRowArc, stock from
        wms.tblInventoryTransactionHeaderArc/RowArc via wms.tblShipPointWarehouseArc, MT conversion
        from itm.tblItemArc. Window - {start} to {now:%Y-%m-%d} (month to date).
        </div>""",
        unsafe_allow_html=True,
    )


if __name__ == "__main__":
    main()
