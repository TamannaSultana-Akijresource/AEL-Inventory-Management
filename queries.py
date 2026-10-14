"""AEL query definitions.

Scope and logic
---------------
  * Business unit : 144 (Akij Essentials Ltd.)
  * Ship points   : the 7 AEL consumer / distribution points (see config.py).
                    "TVS" is the source code for AEL Tejgoan.
  * Only Bag-UOM order lines are reported.
  * MT = bags * itm.tblItemArc.numItemSize (kg/bag) / 1000
  * Stock = running sum of every inventory transaction on record for the
            warehouse(s) mapped to the ship point
            (wms.tblInventoryTransactionHeaderArc / RowArc ->
             wms.tblShipPointWarehouseArc)
  * Diff. = Stock - Variance in Order Quantity
  * OTIF  = delivered / ordered per order line (0..1)
"""

from __future__ import annotations

from config import AEL_SHIPPOINTS, BU

_ship_list = ", ".join("'" + s.replace("'", "''") + "'" for s in AEL_SHIPPOINTS)

SUMMARY_SQL = f"""
WITH stock AS (
    SELECT  sp.strShipPointName AS Shippoint,
            r.intItemId          AS ItemId,
            SUM(r.numTransactionQuantity) AS Stock
    FROM wms.tblInventoryTransactionRowArc r
    JOIN wms.tblInventoryTransactionHeaderArc h
         ON h.intInventoryTransactionId = r.intInventoryTransactionId
    JOIN wms.tblShipPointWarehouseArc spw
         ON spw.intWarehouseId = h.intWarehouseId AND spw.isActive = 1
    JOIN wms.tblShipPointArc sp
         ON sp.intShipPointId = spw.intShipPointId
    WHERE h.isActive = 1
      AND sp.intBusinessUnitId = {BU}
      AND sp.strShipPointName IN ({_ship_list})
    GROUP BY sp.strShipPointName, r.intItemId
),
orders AS (
    SELECT  h.strShippointName      AS Shippoint,
            r.intItemId             AS ItemId,
            r.strItemName           AS ItemName,
            SUM(r.numOrderQuantity)       AS OrderQty,
            SUM(r.numDeliveredQuantity)   AS SalesQty,
            SUM(r.numUndeliveryQuantity)  AS VarQty,
            SUM(r.numOrderValue)          AS OrderValue
    FROM oms.tblSalesOrderHeaderArc h
    JOIN oms.tblSalesOrderRowArc r
         ON r.intSalesOrderId = h.intSalesOrderId
    WHERE h.intBusinessUnitId = {BU}
      AND h.isActive = 1
      AND r.strUOM = 'Bag'
      AND h.strShippointName IN ({_ship_list})
      AND h.dteSalesOrderDate >= '{{start}}'
      AND h.dteSalesOrderDate <  '{{end}}'
    GROUP BY h.strShippointName, r.intItemId, r.strItemName
)
SELECT  o.Shippoint                                        AS [Shippoint Name],
        o.ItemName                                         AS [Item Name],
        o.OrderQty                                         AS [Sum of Order Quantity (Bag)],
        o.SalesQty                                         AS [Sum of Sales Quantity (Bag)],
        o.VarQty                                           AS [Sum of Variance in Order Quantity (Bag)],
        o.OrderValue                                       AS [Order Value],
        ISNULL(s.Stock, 0)                                 AS [Stock],
        ISNULL(s.Stock, 0) - o.VarQty                      AS [Diff.]
FROM orders o
LEFT JOIN stock s
       ON s.Shippoint = o.Shippoint AND s.ItemId = o.ItemId
ORDER BY o.Shippoint, o.ItemName
"""

DETAIL_SQL = f"""
SELECT  h.dteSalesOrderDate                                    AS [SO Date],
        h.strSalesOrderCode                                    AS [SO Code],
        h.strDistributionChannelName                           AS [Channel Name],
        h.strShippointName                                     AS [Shippoint Name],
        h.strSoldToPartnerName                                 AS [Customer Name],
        r.strItemName                                          AS [Item Name],
        r.numOrderQuantity                                     AS [Order Quantity (Bag)],
        r.numOrderQuantity * ISNULL(i.numItemSize, 0) / 1000.0 AS [Order Quantity (MT)],
        r.numOrderValue                                        AS [Total Order Value],
        r.numDeliveredQuantity                                 AS [Sales Quantity (Bag)],
        r.numDeliveredQuantity * ISNULL(i.numItemSize, 0) / 1000.0 AS [Sales Quantity (MT)],
        r.numDeliveredQuantity * r.numItemPrice                AS [Total Sales Value],
        r.numUndeliveryQuantity                                AS [Variance in Order Quantity (Bag)],
        r.numUndeliveryQuantity * ISNULL(i.numItemSize, 0) / 1000.0 AS [Variance in Order Quantity (MT)],
        r.numUndeliveryValues                                  AS [Total Variance in Order Value],
        CASE WHEN r.numOrderQuantity > 0
             THEN r.numDeliveredQuantity / r.numOrderQuantity END AS [OTIF]
FROM oms.tblSalesOrderHeaderArc h
JOIN oms.tblSalesOrderRowArc r
     ON r.intSalesOrderId = h.intSalesOrderId
LEFT JOIN itm.tblItemArc i
     ON i.intItemId = r.intItemId
WHERE h.intBusinessUnitId = {BU}
  AND h.isActive = 1
  AND r.strUOM = 'Bag'
  AND h.strShippointName IN ({_ship_list})
  AND h.dteSalesOrderDate >= '{{start}}'
  AND h.dteSalesOrderDate <  '{{end}}'
ORDER BY h.dteSalesOrderDate DESC, h.strSalesOrderCode, r.strItemName
"""
