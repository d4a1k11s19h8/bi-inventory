#!/usr/bin/env python3
"""
Recompute the dashboard's KPIs straight from the SQLite warehouse, for any date range and filter.
Use it to prove the dashboard shows the right numbers (sir's "set start and end date and verify" check).

Examples
  python etl/verify_kpis.py --from 2026-07-06 --to 2026-10-18
  python etl/verify_kpis.py --from 2026-07-06 --to 2026-10-18 --wh NGP --cat OIL
  python etl/verify_kpis.py --from 2025-09-01 --to 2025-11-02 --by week
  python etl/verify_kpis.py --from 2026-04-01 --to 2026-09-30 --by month --sql

The dashboard works in whole weeks (Monday-Sunday), so any date you give is snapped to the week containing it.
"""
import argparse
import sqlite3
import sys
from datetime import date
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
TARGET_DOI = 20          # dashboard default (Settings tab)


def inr(v):
    a = abs(v)
    s = "-" if v < 0 else ""
    if a >= 1e7:
        return f"{s}Rs {a/1e7:.2f} Cr"
    if a >= 1e5:
        return f"{s}Rs {a/1e5:.2f} L"
    return f"{s}Rs {a:,.0f}"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", default=str(ROOT / "data" / "warehouse" / "inventory_dw.db"))
    ap.add_argument("--from", dest="d_from", required=True)
    ap.add_argument("--to", dest="d_to", required=True)
    ap.add_argument("--wh", default="all", help="NGP BHW PNQ IDR RPR HYD or all")
    ap.add_argument("--cat", default="all", help="STP OIL PKG BEV DRY HCP or all")
    ap.add_argument("--abc", default="all", help="A, B, C or all")
    ap.add_argument("--by", choices=["week", "month", "quarter", "fy", "wh", "cat"], help="show the grouped table (same as the dashboard's Data check tab)")
    ap.add_argument("--sql", action="store_true", help="print the SQL used")
    ap.add_argument("--sup", action="store_true", help="also print the supplier scorecard (receipts inside the range)")
    a = ap.parse_args()

    con = sqlite3.connect(a.db)
    date0 = pd.Timestamp(con.execute("SELECT MIN(date) FROM dim_date WHERE week_index = 0").fetchone()[0])
    nweeks = con.execute("SELECT MAX(week_index)+1 FROM fact_stock_snapshot_weekly").fetchone()[0]
    wk = lambda s: max(0, min(nweeks - 1, (pd.Timestamp(s) - date0).days // 7))
    w0, w1 = wk(a.d_from), wk(a.d_to)
    if w0 > w1:
        sys.exit("--from must be before --to")
    where = ["1=1"]
    if a.wh != "all":
        where.append(f"wh_id = '{a.wh}'")
    if a.cat != "all":
        where.append(f"category_id = '{a.cat}'")
    if a.abc != "all":
        where.append(f"abc_class = '{a.abc}'")
    wsql = " AND ".join(where)
    df = pd.read_sql(f"SELECT * FROM vw_weekly WHERE {wsql}", con)
    rng = df[(df.week_index >= w0) & (df.week_index <= w1)]
    ws = lambda w: (date0 + pd.Timedelta(days=7 * w)).strftime("%d %b %Y")

    print(f"\nRange snapped to weeks {w0+1}-{w1+1} of {nweeks} (week_index {w0}..{w1}):  {ws(w0)}  ->  {(date0 + pd.Timedelta(days=7*w1+6)).strftime('%d %b %Y')}   ({w1-w0+1} weeks)")
    print(f"Filters: warehouse={a.wh}  category={a.cat}  ABC={a.abc}   ({df[['sku_key','wh_key']].drop_duplicates().shape[0]} SKU-locations)\n")

    fill = rng.sales_value_inr.sum() / max(1, rng.demand_value_inr.sum())
    oosr = rng.stockout_days.sum() / max(1, rng.active_days.sum())
    wo = rng.writeoff_value_inr.sum()
    cogs = rng.cogs_value_inr.sum()
    inv_end = df[df.week_index == w1].closing_stock_value_inr.sum()
    inv_open = df[df.week_index == w0 - 1].closing_stock_value_inr.sum() if w0 > 0 else float("nan")
    cogs4 = df[(df.week_index >= w1 - 3) & (df.week_index <= w1)].cogs_value_inr.sum()
    doi = inv_end / (cogs4 / 28) if cogs4 else float("nan")
    rows = [("Fill rate (Rs basis)", f"{fill*100:.2f}%", "sum(sales_value) / sum(demand_value)"),
            ("Stock-out rate", f"{oosr*100:.2f}%", "sum(stockout_days) / sum(active_days)"),
            ("Expiry write-offs", inr(wo), "sum(writeoff_value) at cost"),
            ("Write-off % of cost of sales", f"{wo/cogs*100:.2f}%" if cogs else "n/a", "write-offs / sum(cogs_value)"),
            ("Demand (at price)", inr(rng.demand_value_inr.sum()), ""),
            ("Sales (at price)", inr(rng.sales_value_inr.sum()), ""),
            ("Lost sales (at price)", inr(rng.lost_sales_value_inr.sum()), "demand - sales"),
            ("Received into stock (cost)", inr(rng.receipts_value_inr.sum()), ""),
            ("Cost of sales", inr(cogs), ""),
            ("Opening inventory (cost)", inr(inv_open) if inv_open == inv_open else "n/a", "closing stock of the week before the range"),
            ("Closing inventory (cost)", inr(inv_end), "closing stock of the LAST week (semi-additive: never summed over time)"),
            ("Days of inventory at end week", f"{doi:.1f} d", "closing inventory / (cost of sales of last 4 weeks / 28)"),
            ("Ideal inventory at target DOI", inr(TARGET_DOI * cogs4 / 28), f"{TARGET_DOI} d x daily cost of sales")]
    wdt = max(len(r[0]) for r in rows)
    for n, v, f in rows:
        print(f"  {n:<{wdt}}  {v:>14}   {f}")
    chk = inv_open + rng.receipts_value_inr.sum() - cogs - wo - inv_end
    if inv_open == inv_open:
        print(f"\n  Waterfall check: opening + received - sold - written off - closing = {chk:,.2f}  (should be 0)")

    # ---- supplier scorecard: PO lines RECEIVED inside the range, for the filtered SKU-locations ----
    d_lo = int((date0 + pd.Timedelta(days=7 * w0)).strftime("%Y%m%d"))
    d_hi = int((date0 + pd.Timedelta(days=7 * w1 + 6)).strftime("%Y%m%d"))
    sw = [f"f.received_date_key BETWEEN {d_lo} AND {d_hi}"]
    if a.wh != "all":
        sw.append(f"w.wh_id = '{a.wh}'")
    if a.cat != "all":
        sw.append(f"s.category_id = '{a.cat}'")
    if a.abc != "all":
        sw.append(f"s.abc_class_current = '{a.abc}'")
    sup_sql = f"""SELECT d.supplier_name, COUNT(*) AS receipts, AVG(f.lead_time_days) AS avg_lead_days, AVG(f.planned_lead_time_days) AS avg_plan_days,
       AVG(f.otif_flag) AS otif, AVG(f.on_time_flag) AS on_time, AVG(f.in_full_flag) AS in_full, SUM(f.received_value_inr) AS spend
FROM fact_purchase_order_line f JOIN dim_sku s USING(sku_key) JOIN dim_warehouse w USING(wh_key) JOIN dim_supplier d USING(supplier_key)
WHERE {' AND '.join(sw)} GROUP BY d.supplier_name ORDER BY otif"""
    sd = pd.read_sql(sup_sql, con)
    if len(sd):
        n = sd.receipts.sum()
        print(f"\n  Supplier receipts in range   {n:>10,}   lines received; lead time avg {(sd.avg_lead_days*sd.receipts).sum()/n:.2f} d; "
              f"OTIF {(sd.otif*sd.receipts).sum()/n*100:.2f}%; spend {inr(sd.spend.sum())}")
    if a.sup:
        pd.set_option("display.width", 200)
        t = sd.copy(); t["otif"] = (t.otif * 100).round(1); t["on_time"] = (t.on_time * 100).round(1); t["in_full"] = (t.in_full * 100).round(1)
        t["avg_lead_days"] = t.avg_lead_days.round(2); t["avg_plan_days"] = t.avg_plan_days.round(2); t["spend"] = t.spend.round(0)
        print("\n", t.to_string(index=False))
        if a.sql:
            print("\n-- SQL (supplier scorecard)\n" + sup_sql + ";")

    if a.by:
        g = rng.copy()
        g["month_key"] = pd.to_datetime(g.week_start).dt.strftime("%Y-%m")
        g["quarter_key"] = g.fiscal_year + " " + g.fiscal_quarter
        key = {"week": "week_start", "month": "month_key", "quarter": "quarter_key", "fy": "fiscal_year", "wh": "wh_name", "cat": "category_name"}[a.by]
        agg = g.groupby(key).agg(demand=("demand_value_inr", "sum"), sales=("sales_value_inr", "sum"), lost=("lost_sales_value_inr", "sum"),
                                 receipts=("receipts_value_inr", "sum"), cogs=("cogs_value_inr", "sum"), writeoff=("writeoff_value_inr", "sum"),
                                 so_days=("stockout_days", "sum"), act_days=("active_days", "sum"), last_week=("week_index", "max"))
        agg["fill_%"] = (agg.sales / agg.demand * 100).round(2)
        agg["stockout_%"] = (agg.so_days / agg.act_days * 100).round(2)
        if a.by in ("wh", "cat"):
            last = df[df.week_index == w1].groupby(key).closing_stock_value_inr.sum()
        else:
            cl = df.groupby([key if key in df.columns else None, "week_index"]) if False else None
            tmp = df.copy()
            tmp["month_key"] = pd.to_datetime(tmp.week_start).dt.strftime("%Y-%m")
            tmp["quarter_key"] = tmp.fiscal_year + " " + tmp.fiscal_quarter
            wk_close = tmp.groupby(["week_index", key]).closing_stock_value_inr.sum().reset_index()
            last = pd.Series({k: tmp[tmp.week_index == agg.loc[k, "last_week"]].closing_stock_value_inr.sum() for k in agg.index})
        agg["closing_stock"] = last
        pd.set_option("display.width", 220)
        pd.set_option("display.float_format", lambda v: f"{v:,.2f}")
        print("\n", agg.drop(columns=["last_week"]).to_string())
    if a.sql:
        print(f"""\n-- SQL equivalent (fill rate, stock-out rate, write-offs)
SELECT SUM(sales_value_inr)*1.0/SUM(demand_value_inr) AS fill_rate,
       SUM(stockout_days)*1.0/SUM(active_days)        AS stockout_rate,
       SUM(writeoff_value_inr)                        AS writeoff_value
FROM vw_weekly WHERE week_index BETWEEN {w0} AND {w1} AND {wsql};
-- closing inventory (last week only)
SELECT SUM(closing_stock_value_inr) FROM vw_weekly WHERE week_index = {w1} AND {wsql};""")


if __name__ == "__main__":
    main()
