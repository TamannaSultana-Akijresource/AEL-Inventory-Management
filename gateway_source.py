"""AEL data source backed by the enterprise API gateway.

The gateway's query tool injects an unqualified ``intBusinessUnitId IN (...)``
scope filter. That makes a two-table ``oms.tblSalesOrderHeaderArc`` JOIN
``oms.tblSalesOrderRowArc`` ambiguous (both tables have the column), so instead
we read the base tables separately and join/aggregate in pandas:

  * orders  : tblSalesOrderHeaderArc (order + ship point + date)  -- paged
              + tblSalesOrderRowArc LEFT JOIN itm.tblItemArc (item + qty + size)
  * stock   : the wms transaction join, per ship point, SUM by item       -- paged

Columns produced match what ``dashboard.prepare_summary`` / ``prepare_detail``
expect, so the rest of the app is unchanged.
"""

from __future__ import annotations

import sys

import pandas as pd

import config as C
import gateway_client as gw

PAGE = 500          # gateway max rows per call
ROW_CHUNK = 150     # order ids per row query (keeps rows under PAGE)

_SHIP_LIST = ", ".join("'" + s.replace("'", "''") + "'" for s in C.AEL_SHIPPOINTS)


def _log(msg: str) -> None:
    print(f"[gateway] {msg}", flush=True)


# ---------------------------------------------------------------------------
# Headers (one row per sales order)
# ---------------------------------------------------------------------------
def fetch_headers(start: str, end: str) -> list[dict]:
    out: list[dict] = []
    last = None
    for _ in range(200):  # hard page cap
        keyset = f"AND intSalesOrderId > {int(last)}" if last is not None else ""
        sql = (
            "SELECT intSalesOrderId, strSalesOrderCode, strDistributionChannelName, "
            "strShippointName, strSoldToPartnerName, dteSalesOrderDate "
            "FROM oms.tblSalesOrderHeaderArc "
            f"WHERE intBusinessUnitId = {C.BU} AND isActive = 1 "
            f"AND strShippointName IN ({_SHIP_LIST}) "
            f"AND dteSalesOrderDate >= '{start}' AND dteSalesOrderDate < '{end}' "
            f"{keyset} ORDER BY intSalesOrderId"
        )
        rows = gw.run_query(sql, limit=PAGE)
        out.extend(rows)
        if len(rows) < PAGE:
            break
        last = rows[-1]["intSalesOrderId"]
    _log(f"headers: {len(out)} orders")
    return out


# ---------------------------------------------------------------------------
# Rows (one row per order line, Bag UOM) joined with item size
# ---------------------------------------------------------------------------
_ROW_COLS = (
    "r.intSalesOrderId, r.intItemId, r.strItemName, r.numOrderQuantity, "
    "r.numDeliveredQuantity, r.numUndeliveryQuantity, r.numOrderValue, "
    "r.numItemPrice, r.numUndeliveryValues, i.numItemSize"
)


def _rows_for_chunk(chunk: list[int], out: list[dict]) -> None:
    ids = ",".join(str(i) for i in chunk)
    sql = (
        f"SELECT {_ROW_COLS} "
        "FROM oms.tblSalesOrderRowArc r "
        "LEFT JOIN itm.tblItemArc i ON i.intItemId = r.intItemId "
        f"WHERE r.intSalesOrderId IN ({ids}) AND r.strUOM = 'Bag' "
        "ORDER BY r.intSalesOrderId"
    )
    rows = gw.run_query(sql, limit=PAGE)
    if len(rows) >= PAGE and len(chunk) > 1:
        mid = len(chunk) // 2
        _rows_for_chunk(chunk[:mid], out)
        _rows_for_chunk(chunk[mid:], out)
        return
    if len(rows) >= PAGE:
        _log(f"warning: order {chunk[0]} may have more than {PAGE} bag lines")
    out.extend(rows)


def fetch_rows(order_ids: list[int]) -> list[dict]:
    out: list[dict] = []
    for i in range(0, len(order_ids), ROW_CHUNK):
        _rows_for_chunk(order_ids[i:i + ROW_CHUNK], out)
    _log(f"rows: {len(out)} order lines")
    return out


# ---------------------------------------------------------------------------
# Stock (running sum of inventory transactions per ship point x item)
# ---------------------------------------------------------------------------
_STOCK_SELECT = (
    "SELECT sp.strShipPointName AS Shippoint, r.intItemId AS ItemId, "
    "SUM(r.numTransactionQuantity) AS Stock "
    "FROM wms.tblInventoryTransactionRowArc r "
    "JOIN wms.tblInventoryTransactionHeaderArc h "
    "  ON h.intInventoryTransactionId = r.intInventoryTransactionId "
    "JOIN wms.tblShipPointWarehouseArc spw "
    "  ON spw.intWarehouseId = h.intWarehouseId AND spw.isActive = 1 "
    "JOIN wms.tblShipPointArc sp ON sp.intShipPointId = spw.intShipPointId "
    f"WHERE h.isActive = 1 AND sp.intBusinessUnitId = {C.BU} "
)


def fetch_stock() -> pd.DataFrame:
    records: list[dict] = []
    for ship in C.AEL_SHIPPOINTS:
        esc = ship.replace("'", "''")
        last = None
        for _ in range(200):
            keyset = f"AND r.intItemId > {int(last)}" if last is not None else ""
            sql = (
                f"{_STOCK_SELECT} AND sp.strShipPointName = '{esc}' {keyset} "
                "GROUP BY sp.strShipPointName, r.intItemId ORDER BY r.intItemId"
            )
            rows = gw.run_query(sql, limit=PAGE)
            records.extend(rows)
            if len(rows) < PAGE:
                break
            last = rows[-1]["ItemId"]
    df = pd.DataFrame(records)
    _log(f"stock: {len(df)} ship point x item rows")
    return df


# ---------------------------------------------------------------------------
# Assemble summary + detail
# ---------------------------------------------------------------------------
def _build_detail(headers: list[dict], rows: list[dict]) -> pd.DataFrame:
    by_id = {h["intSalesOrderId"]: h for h in headers}
    zero = {"numItemSize": 0.0, "numOrderValue": 0.0, "numItemPrice": 0.0,
            "numUndeliveryValues": 0.0, "numOrderQuantity": 0.0,
            "numDeliveredQuantity": 0.0, "numUndeliveryQuantity": 0.0}

    recs = []
    for r in rows:
        h = by_id.get(r["intSalesOrderId"])
        if not h:
            continue
        g = {k: (r.get(k) if r.get(k) is not None else v) for k, v in zero.items()}
        size = float(g["numItemSize"] or 0.0)
        oq, sq, vq = g["numOrderQuantity"], g["numDeliveredQuantity"], g["numUndeliveryQuantity"]
        recs.append({
            "_ItemId": r["intItemId"],
            "SO Date": pd.to_datetime(h["dteSalesOrderDate"]),
            "SO Code": h["strSalesOrderCode"],
            "Channel Name": h["strDistributionChannelName"],
            "Shippoint Name": h["strShippointName"],
            "Customer Name": h["strSoldToPartnerName"],
            "Item Name": r["strItemName"],
            "Order Quantity (Bag)": oq,
            "Order Quantity (MT)": oq * size / 1000.0,
            "Total Order Value": g["numOrderValue"],
            "Sales Quantity (Bag)": sq,
            "Sales Quantity (MT)": sq * size / 1000.0,
            "Total Sales Value": sq * g["numItemPrice"],
            "Variance in Order Quantity (Bag)": vq,
            "Variance in Order Quantity (MT)": vq * size / 1000.0,
            "Total Variance in Order Value": g["numUndeliveryValues"],
            "OTIF": (sq / oq) if oq else None,
        })
    return pd.DataFrame(recs)


def _build_summary(detail: pd.DataFrame, stock: pd.DataFrame) -> pd.DataFrame:
    keys = ["Shippoint Name", "Item Name", "_ItemId"]
    agg = detail.groupby(keys, as_index=False).agg({
        "Order Quantity (Bag)": "sum",
        "Sales Quantity (Bag)": "sum",
        "Variance in Order Quantity (Bag)": "sum",
        "Total Order Value": "sum",
    })

    if stock is not None and not stock.empty:
        st = stock.rename(columns={"Shippoint": "Shippoint Name", "ItemId": "_ItemId"})
        agg = agg.merge(st[["Shippoint Name", "_ItemId", "Stock"]],
                        on=["Shippoint Name", "_ItemId"], how="left")
    else:
        agg["Stock"] = 0.0
    agg["Stock"] = agg["Stock"].fillna(0.0)
    agg["Diff."] = agg["Stock"] - agg["Variance in Order Quantity (Bag)"]

    agg = agg.rename(columns={
        "Order Quantity (Bag)": "Sum of Order Quantity (Bag)",
        "Sales Quantity (Bag)": "Sum of Sales Quantity (Bag)",
        "Variance in Order Quantity (Bag)": "Sum of Variance in Order Quantity (Bag)",
        "Total Order Value": "Order Value",
    })
    cols = ["Shippoint Name", "Item Name", "Sum of Order Quantity (Bag)",
            "Sum of Sales Quantity (Bag)", "Sum of Variance in Order Quantity (Bag)",
            "Order Value", "Stock", "Diff."]
    return agg[cols]


def load_live(start: str, end: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return (summary, detail) as raw DataFrames (before Status/Remarks)."""
    headers = fetch_headers(start, end)
    if not headers:
        return pd.DataFrame(), pd.DataFrame()
    rows = fetch_rows([h["intSalesOrderId"] for h in headers])
    detail = _build_detail(headers, rows)
    stock = fetch_stock()
    summary = _build_summary(detail, stock)
    return summary, detail


if __name__ == "__main__":
    s, d = load_live("2026-10-01", "2026-11-01")
    print("summary rows:", len(s))
    print("detail rows :", len(d))
    if not s.empty:
        print(s.head(8).to_string())
