"""Business rules + static HTML dashboard builder (open code edition).

This module turns two DataFrames (summary + detail) into ONE fully
self-contained, interactive ``index.html``. No server, no database, no
external CDN - it renders identically on a laptop and on GitHub Pages.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta

import numpy as np
import pandas as pd

import config as C


# ---------------------------------------------------------------------------
# Dates
# ---------------------------------------------------------------------------
def month_bounds(today: date) -> tuple[str, str]:
    start = today.replace(day=1)
    end = (start + timedelta(days=32)).replace(day=1)
    return start.isoformat(), end.isoformat()


# ---------------------------------------------------------------------------
# Business rules
# ---------------------------------------------------------------------------
def classify(diff: float, stock: float) -> str:
    """Stock < 0 -> Check Again (physically impossible, ledger gap) |
    Diff < 0 -> Risk | 0 to SAFE_BUFFER -> Pay Attention | else Safe."""
    if pd.isna(diff) or pd.isna(stock):
        return "Pay Attention"
    if stock < 0:
        return "Check Again"
    if diff < 0:
        return "Risk"
    if diff <= C.SAFE_BUFFER:
        return "Pay Attention"
    return "Safe"


def remark(row: pd.Series) -> str:
    s, d = row["Stock"], row["Diff."]
    if s < 0:
        return (
            "Stock ledger is negative - physically impossible, points to a missing "
            "opening balance entry, not a real shortage. Verify before acting."
        )
    if d < 0:
        return f"Short by {abs(d):,.0f} bag against open variance"
    if d <= C.SAFE_BUFFER:
        return f"Thin cover - {d:,.0f} bag buffer only"
    return f"Cover of {d:,.0f} bag"


# ---------------------------------------------------------------------------
# Data preparation
# ---------------------------------------------------------------------------
def prepare_summary(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    num = [c for c in df.columns if c not in ("Shippoint Name", "Item Name")]
    for c in num:
        df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0.0)
    df["Shippoint Name"] = df["Shippoint Name"].fillna("(blank)").astype(str).str.strip()
    df["Item Name"] = df["Item Name"].fillna("(blank)").astype(str).str.strip()
    df["Status"] = [classify(r["Diff."], r["Stock"]) for _, r in df.iterrows()]
    df["Remarks"] = [remark(r) for _, r in df.iterrows()]
    return df


def prepare_detail(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.insert(0, "SL", range(1, len(df) + 1))
    text_cols = ("SO Date", "SO Code", "Channel Name", "Shippoint Name",
                 "Customer Name", "Item Name", "SL")
    for c in df.columns:
        if c not in text_cols:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    for c in ("Shippoint Name", "Item Name", "Channel Name", "Customer Name"):
        df[c] = df[c].fillna("(blank)").astype(str).str.strip()
    return df


# ---------------------------------------------------------------------------
# Payload
# ---------------------------------------------------------------------------
def _num(x) -> float:
    try:
        v = float(x)
        return 0.0 if (np.isnan(v) or np.isinf(v)) else round(v, 4)
    except Exception:
        return 0.0


def build_payload(summary: pd.DataFrame, detail: pd.DataFrame,
                  generated_at: datetime, window_start: str,
                  window_end: str, demo: bool = False) -> dict:
    """Convert the two DataFrames into a JSON-serialisable payload."""
    s_rows = []
    for _, r in summary.iterrows():
        s_rows.append({
            "ship": str(r["Shippoint Name"]),
            "item": str(r["Item Name"]),
            "order": _num(r["Sum of Order Quantity (Bag)"]),
            "sales": _num(r["Sum of Sales Quantity (Bag)"]),
            "variance": _num(r["Sum of Variance in Order Quantity (Bag)"]),
            "orderValue": _num(r.get("Order Value", 0.0)),
            "stock": _num(r["Stock"]),
            "diff": _num(r["Diff."]),
            "status": str(r["Status"]),
            "remarks": str(r["Remarks"]),
        })

    d_rows = []
    for _, r in detail.iterrows():
        d = r["SO Date"]
        d_rows.append({
            "date": d.strftime("%Y-%m-%d") if hasattr(d, "strftime") else str(d),
            "code": str(r.get("SO Code", "")),
            "channel": str(r.get("Channel Name", "")),
            "ship": str(r.get("Shippoint Name", "")),
            "customer": str(r.get("Customer Name", "")),
            "item": str(r.get("Item Name", "")),
            "oqBag": _num(r.get("Order Quantity (Bag)", 0)),
            "oqMT": _num(r.get("Order Quantity (MT)", 0)),
            "oqVal": _num(r.get("Total Order Value", 0)),
            "sqBag": _num(r.get("Sales Quantity (Bag)", 0)),
            "sqMT": _num(r.get("Sales Quantity (MT)", 0)),
            "sqVal": _num(r.get("Total Sales Value", 0)),
            "vqBag": _num(r.get("Variance in Order Quantity (Bag)", 0)),
            "vqMT": _num(r.get("Variance in Order Quantity (MT)", 0)),
            "vqVal": _num(r.get("Total Variance in Order Value", 0)),
            "otif": _num(r.get("OTIF", 0)),
        })

    return {
        "title": C.TITLE,
        "generated": generated_at.strftime("%d %B %Y, %I:%M:%S %p"),
        "generatedIso": generated_at.strftime("%Y-%m-%d %H:%M:%S"),
        "windowStart": window_start,
        "windowEnd": window_end,
        "scope": C.AEL_SHIPPOINTS,
        "safeBuffer": C.SAFE_BUFFER,
        "statusOrder": C.STATUS_ORDER,
        "statusColor": C.STATUS_COLOR,
        "statusBg": C.STATUS_BG,
        "summary": s_rows,
        "detail": d_rows,
        "demo": bool(demo),
    }


# ---------------------------------------------------------------------------
# HTML rendering
# ---------------------------------------------------------------------------
def _dump_json(obj) -> str:
    """JSON that is safe to embed inside a <script> tag."""
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c")


_TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>__TITLE__</title>
<style>
:root{
  --ink:#1b232c; --muted:#63707e; --line:#e2e6ea; --panel:#fff; --canvas:#f6f7f9;
  --accent:#2d6a68;
  --risk:#a5231b; --riskbg:#fbeceb; --watch:#9a5b06; --watchbg:#fdf4e6;
  --safe:#14663f; --safebg:#eaf4ee; --data:#54606e; --databg:#eceef1;
}
*{box-sizing:border-box}
body{margin:0;background:var(--canvas);color:var(--ink);
  font-family:"Inter","Segoe UI",system-ui,-apple-system,sans-serif;font-size:14px}
.wrap{max-width:1500px;margin:0 auto;padding:24px 22px 60px}
.hdr{display:flex;justify-content:space-between;align-items:flex-end;gap:16px;
  border-bottom:2px solid var(--ink);padding-bottom:14px}
.hdr h1{font-size:23px;font-weight:650;letter-spacing:-.02em;margin:0}
.hdr .sub{font-size:12.5px;color:var(--muted);margin-top:4px}
.hdr .clock{text-align:right;font-size:12px;color:var(--muted);line-height:1.6;white-space:nowrap}
.hdr .clock b{color:var(--ink)}
.chips{margin:12px 0 4px}
.chip{display:inline-block;padding:2px 9px;border-radius:3px;font-size:11.5px;font-weight:600;
  margin:2px 5px 2px 0;background:var(--panel);border:1px solid var(--line);color:var(--ink)}
.chip.ghost{color:var(--muted)}
.demo{background:#fff6e5;border:1px solid #f0d59a;color:#8a5a06;border-radius:4px;
  padding:9px 12px;font-size:12.5px;margin:12px 0 0;font-weight:600}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:10px;margin:16px 0 4px}
.card{background:var(--panel);border:1px solid var(--line);border-top:3px solid var(--accent);
  border-radius:4px;padding:12px 13px}
.card.risk{border-top-color:var(--risk)} .card.watch{border-top-color:var(--watch)}
.card.safe{border-top-color:var(--safe)} .card.data{border-top-color:var(--data)}
.card .lab{font-size:10.5px;text-transform:uppercase;letter-spacing:.07em;color:var(--muted);font-weight:600}
.card .val{font-size:23px;font-weight:650;letter-spacing:-.02em;margin-top:5px;line-height:1.1}
.card .note{font-size:11.5px;color:var(--muted);margin-top:4px}
.sect{font-size:11.5px;text-transform:uppercase;letter-spacing:.09em;font-weight:700;color:var(--muted);
  margin:26px 0 10px;border-bottom:1px solid var(--line);padding-bottom:6px}
.grid2{display:grid;grid-template-columns:1.15fr 1fr;gap:20px}
.bars{background:var(--panel);border:1px solid var(--line);border-radius:4px;padding:14px 16px}
.bars h3{margin:0 0 12px;font-size:12.5px;font-weight:600;color:var(--muted)}
.bar-row{display:grid;grid-template-columns:1fr;gap:3px;margin-bottom:11px}
.bar-top{display:flex;justify-content:space-between;gap:10px;font-size:12px}
.bar-top .lbl{white-space:nowrap;overflow:hidden;text-overflow:ellipsis;color:var(--ink)}
.bar-top .num{color:var(--muted);font-variant-numeric:tabular-nums}
.bar-track{height:9px;background:var(--canvas);border-radius:2px;overflow:hidden}
.bar-fill{height:100%;background:var(--accent);border-radius:2px}
.bar-fill.risk{background:var(--risk)} .bar-fill.watch{background:var(--watch)}
.controls{background:var(--panel);border:1px solid var(--line);border-radius:4px;padding:14px 16px;margin-bottom:14px}
.row{display:flex;flex-wrap:wrap;gap:14px;align-items:flex-start}
.field{display:flex;flex-direction:column;gap:5px;min-width:210px;flex:1}
.field label{font-size:11px;text-transform:uppercase;letter-spacing:.06em;color:var(--muted);font-weight:600}
input[type=text],select{font:inherit;padding:7px 9px;border:1px solid var(--line);border-radius:3px;background:#fff;color:var(--ink);width:100%}
select[multiple]{height:112px}
.toggles{display:flex;flex-wrap:wrap;gap:8px;margin-top:4px}
.tog{display:inline-flex;align-items:center;gap:6px;font-size:12.5px;font-weight:600;
  padding:4px 10px;border-radius:3px;border:1px solid var(--line);cursor:pointer;user-select:none}
.tog input{accent-color:var(--accent)}
.tog.risk{color:var(--risk);background:var(--riskbg)} .tog.watch{color:var(--watch);background:var(--watchbg)}
.tog.safe{color:var(--safe);background:var(--safebg)} .tog.data{color:var(--data);background:var(--databg)}
.btns{display:flex;gap:8px;flex-wrap:wrap;margin-top:12px}
button{font:inherit;font-weight:600;font-size:12.5px;padding:8px 14px;border-radius:3px;
  border:1px solid var(--ink);background:var(--ink);color:#fff;cursor:pointer}
button.ghost{background:#fff;color:var(--ink)}
button:hover{background:var(--accent);border-color:var(--accent);color:#fff}
.meta-line{font-size:12px;color:var(--muted);margin-bottom:10px}
.meta-line b{color:var(--ink)}
.table-wrap{overflow:auto;background:var(--panel);border:1px solid var(--line);border-radius:4px;max-height:640px}
table{border-collapse:collapse;width:100%;font-size:12px}
thead th{position:sticky;top:0;background:var(--ink);color:#fff;text-align:left;padding:9px 9px;
  font-weight:600;cursor:pointer;white-space:nowrap;z-index:2}
thead th:hover{background:var(--accent)}
thead th .arrow{opacity:.5;font-size:10px;margin-left:4px}
tbody td{border-bottom:1px solid var(--line);padding:7px 9px;white-space:nowrap;font-variant-numeric:tabular-nums}
tbody tr:nth-child(even){background:#fafbfc}
td.num{text-align:right}
td.txt-left{text-align:left}
.pillpick{display:inline-block;padding:2px 8px;border-radius:3px;font-size:11px;font-weight:600}
tr.r-risk td:first-child{box-shadow:inset 3px 0 0 var(--risk)}
tr.r-watch td:first-child{box-shadow:inset 3px 0 0 var(--watch)}
tr.r-safe td:first-child{box-shadow:inset 3px 0 0 var(--safe)}
tr.r-data td:first-child{box-shadow:inset 3px 0 0 var(--data)}
.empty{padding:26px;text-align:center;color:var(--muted)}
.foot{margin-top:34px;padding-top:14px;border-top:1px solid var(--line);font-size:11.5px;color:var(--muted);line-height:1.75}
details>summary{cursor:pointer;font-weight:600;color:var(--ink);font-size:13px;padding:6px 0}
@media (max-width:920px){.grid2{grid-template-columns:1fr}.hdr{flex-direction:column;align-items:flex-start}}
@media print{.controls{display:none}.table-wrap{max-height:none;overflow:visible}body{background:#fff}}
</style>
</head>
<body>
<div class="wrap">
  <div class="hdr">
    <div>
      <h1 id="h-title"></h1>
      <div class="sub" id="h-sub"></div>
    </div>
    <div class="clock">
      <div>Dhaka time &nbsp;<b id="h-now"></b></div>
      <div>Generated &nbsp;<b id="h-gen"></b></div>
    </div>
  </div>

  <div class="chips" id="h-chips"></div>
  <div id="demo-banner"></div>

  <div class="cards" id="kpi-top"></div>
  <div class="cards" id="kpi-bot"></div>

  <div class="sect">Where the exposure sits</div>
  <div class="grid2">
    <div class="bars"><h3>Largest confirmed shortfalls (bag) - excludes Check Again</h3><div id="chart-risk"></div></div>
    <div class="bars"><h3>Open variance by ship point (bag)</h3><div id="chart-var"></div></div>
  </div>

  <div class="sect">Filters</div>
  <div class="controls">
    <div class="row">
      <div class="field" style="flex:2">
        <label>Search (spelling tolerant)</label>
        <input type="text" id="f-search" placeholder="Ship point, item, customer...">
      </div>
      <div class="field"><label>Ship point</label><select id="f-ship" multiple></select></div>
      <div class="field"><label>Item</label><select id="f-item" multiple></select></div>
    </div>
    <div class="field" style="margin-top:10px">
      <label>Status</label>
      <div class="toggles" id="f-status"></div>
    </div>
    <div class="btns">
      <button id="b-all" class="ghost">Select all</button>
      <button id="b-clear" class="ghost">Clear all</button>
      <button id="b-reset" class="ghost">Reset filters</button>
      <button id="b-csv-sum">Download summary CSV</button>
      <button id="b-csv-det">Download order history CSV</button>
    </div>
  </div>

  <div class="meta-line" id="meta-line"></div>

  <div class="sect">Ship point x item - coverage against open variance</div>
  <div class="table-wrap"><table id="t-summary"><thead></thead><tbody></tbody></table></div>

  <div class="sect" id="detail-head">Sales order history</div>
  <div class="table-wrap"><table id="t-detail"><thead></thead><tbody></tbody></table></div>

  <div class="foot" id="foot"></div>
</div>

<script id="payload" type="application/json">__PAYLOAD__</script>
<script>
const D = JSON.parse(document.getElementById("payload").textContent);
const SCO = D.statusColor, SBG = D.statusBg, SORDER = D.statusOrder;
const SKEY = {"Risk":"risk","Pay Attention":"watch","Safe":"safe","Check Again":"data"};

/* ---------- helpers ---------- */
const fmtInt = v => (v==null||isNaN(v)) ? "" : Math.round(v).toLocaleString("en-US");
const fmt1 = v => (v==null||isNaN(v)) ? "" : Number(v).toLocaleString("en-US",{minimumFractionDigits:1,maximumFractionDigits:1});
const fmt2 = v => (v==null||isNaN(v)) ? "" : Number(v).toLocaleString("en-US",{minimumFractionDigits:2,maximumFractionDigits:2});
const fmtMoney = v => (v==null||isNaN(v)) ? "" : Math.round(v).toLocaleString("en-US");
const esc = s => String(s??"").replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
const norm = s => String(s??"").toLowerCase().replace(/[^a-z0-9 ]/g,"").trim();

function seqRatio(a,b){
  if(a===b) return 1; if(!a.length||!b.length) return 0;
  const m=a.length,n=b.length, prev=new Array(n+1).fill(0), cur=new Array(n+1).fill(0);
  for(let i=1;i<=m;i++){ for(let j=1;j<=n;j++){ cur[j]=a[i-1]===b[j-1]?prev[j-1]+1:Math.max(prev[j],cur[j-1]); } for(let j=0;j<=n;j++) prev[j]=cur[j]; }
  return 2*prev[n]/(m+n);
}
function fuzzyScore(opt,q){ const o=norm(opt),qq=norm(q); if(!qq) return 1; if(o.indexOf(qq)>=0) return 1;
  let best=seqRatio(qq,o); o.split(" ").forEach(w=>best=Math.max(best,seqRatio(qq,w)));
  const qw=qq.split(" "); if(qw.length>1){ let s=0; qw.forEach(w=>{let b=0;o.split(" ").forEach(ow=>b=Math.max(b,seqRatio(w,ow)));s+=b;}); best=Math.max(best,s/qw.length);} return best; }
function fuzzyFilter(opts,q){ if(!q.trim()) return opts.slice();
  let sc=opts.map(o=>[o,fuzzyScore(o,q)]); let hit=sc.filter(x=>x[1]>=0.62);
  if(!hit.length) hit=sc.filter(x=>x[1]>=0.45).slice(0,40);
  return hit.sort((a,b)=>b[1]-a[1]).map(x=>x[0]); }

/* ---------- state ---------- */
const state = { search:"", ships:null, items:null, status:new Set(SORDER), sortS:{k:"order",d:-1}, sortD:{k:"date",d:-1} };

function uniq(arr){ return [...new Set(arr)].filter(x=>x!==""); }

/* ---------- header ---------- */
document.getElementById("h-title").textContent = D.title;
document.getElementById("h-sub").innerHTML = "Month to date &middot; window " + D.windowStart + " to " + D.windowEnd
  + " &middot; " + D.scope.length + " ship points &middot; sales orders against live warehouse stock";
document.getElementById("h-now").textContent = D.generated;
document.getElementById("h-gen").textContent = D.generated;
document.getElementById("h-chips").innerHTML = D.scope.map(s=>'<span class="chip">'+esc(s)+'</span>').join("")
  + '<span class="chip ghost">AEL Tejgoan = TVS in source</span>';
if(D.demo){ document.getElementById("demo-banner").innerHTML =
  '<div class="demo">DEMO DATA &middot; This dashboard was generated in demo mode because no live database connection was available. Replace it by running <b>run_daily.bat</b>.</div>'; }

/* ---------- filter controls ---------- */
const allShips = uniq(D.summary.map(r=>r.ship)).sort();
const allItems = uniq(D.summary.map(r=>r.item)).sort();
function optsHtml(list,sel){ return list.map(o=>'<option value="'+esc(o)+'"'+(sel&&sel.has(o)?" selected":"")+'>'+esc(o)+'</option>').join(""); }

function buildControls(){
  const shipSel=document.getElementById("f-ship"), itemSel=document.getElementById("f-item");
  shipSel.innerHTML=optsHtml(allShips,null); itemSel.innerHTML=optsHtml(allItems,null);
  const st=document.getElementById("f-status"); st.innerHTML="";
  SORDER.forEach(s=>{ const id="st_"+SKEY[s];
    const l=document.createElement("label"); l.className="tog "+SKEY[s];
    l.innerHTML='<input type="checkbox" id="'+id+'" checked>'+esc(s); st.appendChild(l);
    l.querySelector("input").addEventListener("change",()=>{ l.querySelector("input").checked?state.status.add(s):state.status.delete(s); render(); });
  });
}

function resetFilterState(){
  state.search=""; state.status=new Set(SORDER); state.ships=null; state.items=null;
  document.getElementById("f-search").value="";
  [...document.getElementById("f-ship").options].forEach(o=>o.selected=false);
  [...document.getElementById("f-item").options].forEach(o=>o.selected=false);
  buildControls();
}

function currentShips(){ const s=[...document.getElementById("f-ship").selectedOptions].map(o=>o.value); return s.length?s:allShips; }
function currentItems(){ const s=[...document.getElementById("f-item").selectedOptions].map(o=>o.value); return s.length?s:allItems; }
function shipOptions(){ return state.search ? fuzzyFilter(allShips,state.search) : allShips; }
function itemOptions(){ return state.search ? fuzzyFilter(allItems,state.search) : allItems; }

function applySearchUpdate(){
  // Rebuild ship/item option lists based on the search box (like the Streamlit app).
  const sSel=new Set(currentShips()), iSel=new Set(currentItems());
  let so=shipOptions(), io=itemOptions();
  if(state.search.trim()){ if(so.length && !io.length) io=allItems; else if(io.length && !so.length) so=allShips; }
  document.getElementById("f-ship").innerHTML=optsHtml(so, sSel);
  document.getElementById("f-item").innerHTML=optsHtml(io, iSel);
}

/* ---------- filtering ---------- */
function filteredSummary(){
  const ships=new Set(currentShips()), items=new Set(currentItems()), q=state.search.trim();
  let custHits=null;
  if(q){ custHits=new Set(fuzzyFilter(uniq(D.detail.map(r=>r.customer)),q));
         if(!custHits.size){ const so=fuzzyFilter(allShips,q), io=fuzzyFilter(allItems,q); custHits=new Set([...so,...io]); } }
  return D.summary.filter(r=>{
    if(!ships.has(r.ship)||!items.has(r.item)) return false;
    if(!state.status.has(r.status)) return false;
    if(q){ if(!custHits.has(r.ship)&&!custHits.has(r.item)) return false; }
    return true;
  });
}
function filteredDetail(){
  const ships=new Set(currentShips()), items=new Set(currentItems()), q=state.search.trim();
  return D.detail.filter(r=>{
    if(!ships.has(r.ship)||!items.has(r.item)) return false;
    if(!q) return true;
    return fuzzyScore(r.ship,q)>=0.55 || fuzzyScore(r.item,q)>=0.55 || fuzzyScore(r.customer,q)>=0.55
        || fuzzyScore(r.channel,q)>=0.55 || fuzzyScore(r.code,q)>=0.55;
  });
}

/* ---------- KPI + charts ---------- */
function renderKpis(rows){
  const sum=k=>rows.reduce((a,r)=>a+(Number(r[k])||0),0);
  const order=sum("order"), sales=sum("sales"), variance=sum("variance"), stock=sum("stock"), orderValue=sum("orderValue");
  const fill=order? sales/order*100 : 0;
  const cnt=st=>rows.filter(r=>r.status===st).length;
  const riskGap=Math.abs(rows.filter(r=>r.status==="Risk").reduce((a,r)=>a+(Number(r.diff)||0),0));
  const ships=uniq(rows.map(r=>r.ship)).length, items=uniq(rows.map(r=>r.item)).length;
  const card=(lab,val,note,tone)=> '<div class="card '+(tone||"")+'"><div class="lab">'+lab+'</div><div class="val">'+val+'</div><div class="note">'+note+'</div></div>';
  document.getElementById("kpi-top").innerHTML =
    card("Order quantity",fmtInt(order),fmt2(orderValue/1e6)+" M order value &middot; bag")
   +card("Sales quantity",fmtInt(sales),"Fill rate "+fmt1(fill)+"% of ordered")
   +card("Open variance",fmtInt(variance),"Ordered but not yet delivered &middot; bag")
   +card("Stock on hand",fmtInt(stock),fmtInt(rows.length)+" ship point x item lines");
  document.getElementById("kpi-bot").innerHTML =
    card("At risk",fmtInt(cnt("Risk")),"Short by "+fmtInt(riskGap)+" bag in total","risk")
   +card("Check data",fmtInt(cnt("Check Again")),"Ledger shows negative stock - verify","data")
   +card("Pay attention",fmtInt(cnt("Pay Attention")),"Cover between 0 and "+D.safeBuffer+" bag","watch")
   +card("Safe",fmtInt(cnt("Safe")),"Cover above "+D.safeBuffer+" bag","safe")
   +card("Ship points live",fmtInt(ships),fmtInt(items)+" distinct items");
}

function bars(el, data, tone){
  if(!data.length){ el.innerHTML='<div class="empty">No data in the current selection.</div>'; return; }
  const max=Math.max(...data.map(d=>Math.abs(d.v)))||1;
  el.innerHTML=data.map(d=>'<div class="bar-row"><div class="bar-top"><span class="lbl" title="'+esc(d.l)+'">'+esc(d.l)
    +'</span><span class="num">'+fmtInt(d.v)+'</span></div><div class="bar-track"><div class="bar-fill '+(tone||"")
    +'" style="width:'+Math.max(2,Math.abs(d.v)/max*100)+'%"></div></div></div>').join("");
}
function renderCharts(rows){
  const risk=rows.filter(r=>r.status==="Risk").map(r=>({l:r.item+"  -  "+r.ship,v:Math.abs(r.diff)}))
    .sort((a,b)=>b.v-a.v).slice(0,10);
  const byShip={}; rows.forEach(r=>{byShip[r.ship]=(byShip[r.ship]||0)+(Number(r.variance)||0);});
  const varr=Object.entries(byShip).map(([l,v])=>({l,v})).sort((a,b)=>b.v-a.v).slice(0,10);
  bars(document.getElementById("chart-risk"), risk, "risk");
  bars(document.getElementById("chart-var"), varr, "");
}

/* ---------- tables ---------- */
const SUM_COLS=[
 {k:"ship",t:"Shippoint Name",type:"txt"},
 {k:"item",t:"Item Name",type:"txt"},
 {k:"order",t:"Order Qty (Bag)",type:"int"},
 {k:"sales",t:"Sales Qty (Bag)",type:"int"},
 {k:"variance",t:"Variance (Bag)",type:"int"},
 {k:"stock",t:"Stock",type:"int"},
 {k:"diff",t:"Diff.",type:"int"},
 {k:"status",t:"Status",type:"status"},
 {k:"remarks",t:"Remarks",type:"txt"}
];
const DET_COLS=[
 {k:"date",t:"SO Date",type:"txt"},{k:"code",t:"SO Code",type:"txt"},{k:"channel",t:"Channel",type:"txt"},
 {k:"ship",t:"Shippoint",type:"txt"},{k:"customer",t:"Customer",type:"txt"},{k:"item",t:"Item",type:"txt"},
 {k:"oqBag",t:"Order (Bag)",type:"int"},{k:"oqMT",t:"Order (MT)",type:"mt"},{k:"oqVal",t:"Order Value",type:"num"},
 {k:"sqBag",t:"Sales (Bag)",type:"int"},{k:"sqMT",t:"Sales (MT)",type:"mt"},{k:"sqVal",t:"Sales Value",type:"num"},
 {k:"vqBag",t:"Var (Bag)",type:"int"},{k:"vqMT",t:"Var (MT)",type:"mt"},{k:"vqVal",t:"Var Value",type:"num"},
 {k:"otif",t:"OTIF",type:"pct"}
];
function cellVal(v,type){
  if(v==null||v==="") return "";
  if(type==="int") return fmtInt(v); if(type==="mt"||type==="num") return fmt2(v);
  if(type==="pct") return fmt1(v*100)+"%"; return esc(v);
}
function drawTable(tableId, cols, rows, sort, onSort){
  const th=document.querySelector("#"+tableId+" thead"), tb=document.querySelector("#"+tableId+" tbody");
  th.innerHTML="<tr>"+cols.map(c=>'<th data-k="'+c.k+'">'+esc(c.t)
    +(sort.k===c.k?('<span class="arrow">'+(sort.d<0?"\u25BC":"\u25B2")+'</span>'):"")+'</th>').join("")+"</tr>";
  th.querySelectorAll("th").forEach(el=>el.addEventListener("click",()=>onSort(el.dataset.k)));
  if(!rows.length){ tb.innerHTML='<tr><td class="empty" colspan="'+cols.length+'">No rows match the current filters.</td></tr>'; return; }
  tb.innerHTML=rows.map(r=>{
    const cls = cols[0].k==="ship" ? ("r-"+SKEY[r.status]) : "";
    return '<tr class="'+cls+'">'+cols.map(c=>{
      if(c.type==="status"){ return '<td><span class="pillpick" style="color:'+(SCO[r.status]||"")
        +';background:'+(SBG[r.status]||"")+'">'+esc(r.status)+'</span></td>'; }
      const num=c.type!=="txt";
      return '<td class="'+(num?"num":"txt-left")+'">'+cellVal(r[c.k],c.type)+'</td>';
    }).join("")+"</tr>";
  }).join("");
}
function sortRows(rows, col, dir){
  const t=col.type, k=col.k;
  return rows.slice().sort((a,b)=>{
    let x=a[k], y=b[k];
    if(t==="status"){ x=SORDER.indexOf(x); y=SORDER.indexOf(y); return (x-y)*dir; }
    if(t==="int"||t==="num"||t==="mt"||t==="pct"){ return ((Number(x)||0)-(Number(y)||0))*dir; }
    return String(x).localeCompare(String(y))*dir;
  });
}

/* ---------- render ---------- */
function render(){
  const sRows=filteredSummary(), dRows=filteredDetail();
  renderKpis(sRows); renderCharts(sRows);
  const sCols=SUM_COLS, dCols=DET_COLS;
  drawTable("t-summary", sCols, sortRows(sRows, sCols.find(c=>c.k===state.sortS.k), state.sortS.d),
    state.sortS, k=>{ state.sortS.d = (state.sortS.k===k)? -state.sortS.d : (k==="ship"||k==="item"?1:-1); state.sortS.k=k; render(); });
  drawTable("t-detail", dCols, sortRows(dRows, dCols.find(c=>c.k===state.sortD.k), state.sortD.d),
    state.sortD, k=>{ state.sortD.d = (state.sortD.k===k)? -state.sortD.d : -1; state.sortD.k=k; render(); });
  document.getElementById("detail-head").textContent = "Sales order history - " + dRows.length.toLocaleString() + " lines";
  document.getElementById("meta-line").innerHTML = "<b>"+sRows.length.toLocaleString()+"</b> summary lines &middot; <b>"
    +dRows.length.toLocaleString()+"</b> order lines &middot; ship points: "+currentShips().length
    +" &middot; items: "+currentItems().length+" &middot; statuses: "+[...state.status].join(", ");
}

/* ---------- export ---------- */
function toCSV(cols, rows){ const head=cols.map(c=>'"'+c.t.replace(/"/g,'""')+'"').join(",");
  const body=rows.map(r=>cols.map(c=>{ let v=r[c.k]; if(c.type==="pct") v=(Number(v)||0); return '"'+String(v??"").replace(/"/g,'""')+'"'; }).join(",")).join("\n");
  return head+"\n"+body; }
function download(name, text){ const b=new Blob([text],{type:"text/csv;charset=utf-8"}); const a=document.createElement("a");
  a.href=URL.createObjectURL(b); a.download=name; a.click(); URL.revokeObjectURL(a.href); }

/* ---------- wiring ---------- */
document.getElementById("f-search").addEventListener("input", e=>{ state.search=e.target.value; applySearchUpdate(); render(); });
document.getElementById("f-ship").addEventListener("change", render);
document.getElementById("f-item").addEventListener("change", render);
document.getElementById("b-all").addEventListener("click", ()=>{ [...document.getElementById("f-ship").options].forEach(o=>o.selected=true);
  [...document.getElementById("f-item").options].forEach(o=>o.selected=true); render(); });
document.getElementById("b-clear").addEventListener("click", ()=>{ [...document.getElementById("f-ship").options].forEach(o=>o.selected=false);
  [...document.getElementById("f-item").options].forEach(o=>o.selected=false); render(); });
document.getElementById("b-reset").addEventListener("click", ()=>{ resetFilterState(); render(); });
document.getElementById("b-csv-sum").addEventListener("click", ()=>{
  const rows=sortRows(filteredSummary(), SUM_COLS.find(c=>c.k===state.sortS.k), state.sortS.d);
  download("ael_mtd_coverage_"+D.generatedIso.slice(0,10)+".csv", toCSV(SUM_COLS, rows)); });
document.getElementById("b-csv-det").addEventListener("click", ()=>{
  const rows=sortRows(filteredDetail(), DET_COLS.find(c=>c.k===state.sortD.k), state.sortD.d);
  download("ael_sales_order_history_"+D.generatedIso.slice(0,10)+".csv", toCSV(DET_COLS, rows)); });

document.getElementById("foot").innerHTML =
  "Scope &middot; "+D.scope.length+" AEL ship points. \"AEL Tejgoan\" is recorded in the source system under ship point code \"TVS\"; the two are merged here.<br>"
 +"Stock is the running sum of every inventory transaction on record for the warehouse(s) mapped to the ship point. Where a warehouse log has no opening-balance entry the sum can go negative even though physical stock cannot - those lines are marked <b>Check Again</b> rather than Risk.<br>"
 +"Diff. = Stock - Variance in Order Quantity. Status: <b>Risk</b> Diff &lt; 0 &middot; <b>Pay Attention</b> 0-"+D.safeBuffer+" &middot; <b>Safe</b> &gt; "+D.safeBuffer+" &middot; <b>Check Again</b> Stock &lt; 0.<br>"
 +"Source &middot; DWH: oms.tblSalesOrderHeaderArc + oms.tblSalesOrderRowArc, stock from wms.tblInventoryTransactionHeaderArc/RowArc via wms.tblShipPointWarehouseArc, MT conversion from itm.tblItemArc.<br>"
 +"Window &middot; "+D.windowStart+" to "+D.windowEnd+" (month to date). Generated "+D.generated+".";

buildControls();
render();
</script>
</body>
</html>
"""


def render_html(payload: dict) -> str:
    return (
        _TEMPLATE
        .replace("__TITLE__", payload["title"])
        .replace("__PAYLOAD__", _dump_json(payload))
    )


def build_html(summary: pd.DataFrame, detail: pd.DataFrame,
               generated_at: datetime, window_start: str, window_end: str,
               demo: bool = False) -> str:
    payload = build_payload(summary, detail, generated_at, window_start, window_end, demo=demo)
    return render_html(payload)
