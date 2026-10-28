#!/usr/bin/env python3
"""
Batch ETL for the Inventory Control Tower (CSL430 BI project)

   RAW operational extracts (ERP / WMS style CSVs)        data/raw/*.csv
        |  EXTRACT   read with explicit types, parse dates
        |  VALIDATE  keys, duplicates, negatives, stock-balance identity, batch-vs-ledger tie-out
        |  TRANSFORM conform dimensions (surrogate keys, fiscal calendar, festival flags,
        |            SCD Type 2 history of ABC class), build facts at three grains,
        |            build an aggregate fact, derive current-position attributes
        v  LOAD      CSV files + SQLite database                 data/warehouse/
        v  SERVE     compact JSON for the dashboard             web/data.json

Run:  python etl/run_etl.py            (from the repository root)
"""
import argparse
import json
import sqlite3
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
CHECKS = []


def check(name, ok, detail=""):
    CHECKS.append({"check": name, "status": "PASS" if ok else "FAIL", "detail": str(detail)})
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f"  ({detail})" if detail else ""))
    return ok


# ----------------------------------------------------------------------------------------
# 1. EXTRACT
# ----------------------------------------------------------------------------------------
def extract(raw: Path):
    print("\n[1/5] EXTRACT  reading raw operational extracts from", raw)
    rd = lambda f, **kw: pd.read_csv(raw / f, **kw)
    cat = rd("category_master.csv")
    wh = rd("warehouse_master.csv")
    sup = rd("supplier_master.csv")
    sku = rd("sku_master.csv")
    fest = rd("festival_calendar.csv", parse_dates=["date"])
    mv = rd("daily_movements.csv", parse_dates=["date"],
            dtype={"sku_id": "string", "wh_id": "string"})
    po = rd("purchase_order_lines.csv", parse_dates=["order_date", "promised_date", "received_date"])
    bt = rd("stock_batches.csv", parse_dates=["received_date"])
    terms = rd("sku_supplier_terms.csv")
    for n, d in [("category", cat), ("warehouse", wh), ("supplier", sup), ("sku", sku), ("sku_supplier_terms", terms), ("festival", fest),
                 ("daily_movements", mv), ("purchase_order_lines", po), ("stock_batches", bt)]:
        print(f"  {n:<22}{len(d):>9,} rows")
    return cat, wh, sup, sku, fest, mv, po, bt, terms


# ----------------------------------------------------------------------------------------
# 2. VALIDATE (source side)
# ----------------------------------------------------------------------------------------
def validate_raw(cat, wh, sup, sku, mv, po, bt, terms):
    print("\n[2/5] VALIDATE  source data quality")
    ok = True
    ok &= check("master keys are unique", sku.sku_id.is_unique and wh.wh_id.is_unique and sup.supplier_id.is_unique)
    ok &= check("every SKU maps to a known category and supplier",
                sku.category_id.isin(cat.category_id).all() and sku.primary_supplier_id.isin(sup.supplier_id).all())
    ok &= check("no nulls in movement keys/measures", not mv.isna().any().any())
    ok &= check("no duplicate (date, sku, warehouse) rows", not mv.duplicated(["date", "sku_id", "wh_id"]).any())
    n_exp = len(sku) * len(wh) * mv.date.nunique()
    ok &= check("complete grid: SKUs x warehouses x days", len(mv) == n_exp, f"{len(mv):,} = {n_exp:,}")
    num = ["demand_units", "sales_units", "receipts_units", "orders_placed_units", "writeoff_units", "closing_stock_units"]
    ok &= check("no negative quantities", (mv[num] >= 0).all().all())
    ok &= check("sales never exceed demand", (mv.sales_units <= mv.demand_units).all())
    m = mv.sort_values(["sku_id", "wh_id", "date"])
    prev = m.groupby(["sku_id", "wh_id"]).closing_stock_units.shift(1)
    delta = (prev + m.receipts_units - m.sales_units - m.writeoff_units - m.closing_stock_units).dropna()
    ok &= check("stock balance: closing = previous closing + receipts - sales - write-off", (delta.abs() < 1e-6).all(),
                f"{len(delta):,} day-rows tested")
    ok &= check("PO lines: received on/after ordered, qty received <= ordered",
                ((po.received_date.isna()) | (po.received_date >= po.order_date)).all() and (po.qty_received <= po.qty_ordered).all())
    g = terms.groupby("sku_id")
    ok &= check("sourcing: every SKU has 1-5 suppliers and exactly one primary",
                (g.size().between(1, 5)).all() and (g.is_primary.sum() == 1).all() and set(terms.sku_id) == set(sku.sku_id),
                f"{len(terms)} SKU-supplier terms, {g.size().max()} max per SKU")
    ok &= check("sourcing: allocation shares sum to 1 per SKU", ((g.allocation_share.sum() - 1).abs() < 0.011).all())
    ok &= check("sourcing: primary supplier in terms = primary_supplier_id in SKU master",
                terms[terms.is_primary == 1].set_index("sku_id").supplier_id.reindex(sku.sku_id).values.tolist() == sku.primary_supplier_id.tolist())
    pk = po.merge(terms, on=["sku_id", "supplier_id"], how="left")
    ok &= check("every PO line is placed with an approved supplier of that SKU at its quoted price",
                pk.quoted_unit_price_inr.notna().all() and ((pk.unit_price_inr - pk.quoted_unit_price_inr).abs() < 1e-6).all(), f"{len(po):,} PO lines")
    asof = mv.date.max()
    last = mv[mv.date == asof].set_index(["sku_id", "wh_id"]).closing_stock_units
    b = bt.groupby(["sku_id", "wh_id"]).qty_on_hand.sum()
    b = b.reindex(last.index).fillna(0)
    ok &= check("WMS batch report ties to stock ledger at as-of date", (b - last).abs().max() < 1e-6, f"max diff {(b - last).abs().max():.0f}")
    return ok


# ----------------------------------------------------------------------------------------
# 3. TRANSFORM
# ----------------------------------------------------------------------------------------
def build_dim_date(d0, d1, fest):
    print("\n[3/5] TRANSFORM  conforming dimensions and building facts")
    days = pd.date_range(d0 - timedelta(days=60), d1, freq="D")
    dd = pd.DataFrame({"date": days})
    dd["date_key"] = dd.date.dt.strftime("%Y%m%d").astype(int)
    dd["day_name"] = dd.date.dt.day_name()
    dd["is_weekend"] = (dd.date.dt.dayofweek >= 5).astype(int)
    dd["week_start"] = dd.date - pd.to_timedelta(dd.date.dt.dayofweek, unit="D")
    dd["week_index"] = ((dd.week_start - pd.Timestamp(d0)).dt.days // 7).astype(int)  # <0 = warm-up weeks before the data window
    dd["iso_week"] = dd.date.dt.isocalendar().week.astype(int)
    dd["month"] = dd.date.dt.month
    dd["month_name"] = dd.date.dt.strftime("%b %Y")
    dd["calendar_quarter"] = "Q" + dd.date.dt.quarter.astype(str)
    fy_end = np.where(dd.date.dt.month >= 4, dd.date.dt.year + 1, dd.date.dt.year)
    dd["fiscal_year"] = "FY" + pd.Series(fy_end % 100, index=dd.index).astype(str).str.zfill(2)            # fiscal year runs April-March
    fm = (dd.date.dt.month - 3 - 1) % 12 + 1
    dd["fiscal_month"] = fm
    dd["fiscal_quarter"] = "Q" + ((fm - 1) // 3 + 1).astype(str)
    dd["festival_name"] = ""
    dd["is_festival_window"] = 0
    windows = {"Diwali": 21, "Dussehra": 9, "Holi": 6}   # days of build-up before the festival
    for _, f in fest.iterrows():
        w = windows[f.festival]
        m = (dd.date > f.date - timedelta(days=w + 1)) & (dd.date <= f.date)
        dd.loc[m, "festival_name"] = f.festival
        dd.loc[m, "is_festival_window"] = 1
    return dd


def abc_from_revenue(rev):
    """A = first 70% of cumulative revenue, B = next 20%, C = last 10% (rule is evaluated BEFORE adding the item)."""
    s = rev.sort_values(ascending=False)
    prev = s.cumsum() - s
    tot = s.sum()
    cls = np.where(prev < 0.70 * tot, "A", np.where(prev < 0.90 * tot, "B", "C"))
    return pd.Series(cls, index=s.index).reindex(rev.index)


def transform(cat, wh, sup, sku, fest, mv, po, bt, terms):
    d0, d1 = mv.date.min(), mv.date.max()
    dim_date = build_dim_date(d0, d1, fest)

    dim_wh = wh.rename(columns={"wh_name": "wh_name"}).copy()
    dim_wh.insert(0, "wh_key", range(1, len(dim_wh) + 1))

    dim_sup = sup.copy()
    dim_sup.insert(0, "supplier_key", range(1, len(dim_sup) + 1))
    dim_sup["effective_from"] = d0.date()          # SCD2 columns: planned lead time can change over time
    dim_sup["effective_to"] = date(9999, 12, 31)
    dim_sup["is_current"] = 1

    dim_sku = sku.merge(cat, on="category_id", how="left").merge(
        dim_sup[["supplier_id", "supplier_key"]], left_on="primary_supplier_id", right_on="supplier_id", how="left")
    dim_sku.insert(0, "sku_key", range(1, len(dim_sku) + 1))
    dim_sku = dim_sku[["sku_key", "sku_id", "sku_name", "category_id", "category_name", "short_name", "shelf_life_days",
                       "unit_cost_inr", "mrp_inr", "moq_units", "case_pack_units", "supplier_key"]]
    dim_sku = dim_sku.rename(columns={"short_name": "category_short"})

    # ---- bridge_sku_supplier: many-to-many (one product, several approved suppliers) with a weighting factor ----
    smap0 = dict(zip(dim_sup.supplier_id, dim_sup.supplier_key))
    kmap0 = dict(zip(dim_sku.sku_id, dim_sku.sku_key))
    bridge = terms.copy()
    bridge["sku_key"] = bridge.sku_id.map(kmap0).astype(int)
    bridge["supplier_key"] = bridge.supplier_id.map(smap0).astype(int)
    std_cost = dict(zip(dim_sku.sku_key, dim_sku.unit_cost_inr))
    bridge["price_vs_standard_pct"] = ((bridge.quoted_unit_price_inr / bridge.sku_key.map(std_cost) - 1) * 100).round(2)
    bridge = bridge[["sku_key", "supplier_key", "is_primary", "quoted_unit_price_inr", "quoted_lead_time_days", "allocation_share",
                     "price_vs_standard_pct"]].sort_values(["sku_key", "is_primary", "supplier_key"], ascending=[True, False, True]).reset_index(drop=True)

    kmap = dict(zip(dim_sku.sku_id, dim_sku.sku_key))
    wmap = dict(zip(dim_wh.wh_id, dim_wh.wh_key))
    smap = dict(zip(dim_sup.supplier_id, dim_sup.supplier_key))
    price = dict(zip(dim_sku.sku_key, dim_sku.mrp_inr))
    cost = dict(zip(dim_sku.sku_key, dim_sku.unit_cost_inr))

    # ---- fact_stock_movement_daily (transaction grain: SKU x warehouse x day) ----
    f = mv.copy()
    f["date_key"] = f.date.dt.strftime("%Y%m%d").astype(int)
    f["sku_key"] = f.sku_id.map(kmap).astype(int)
    f["wh_key"] = f.wh_id.map(wmap).astype(int)
    f["lost_units"] = f.demand_units - f.sales_units
    f["stockout_flag"] = (f.closing_stock_units <= 0).astype(int)
    f = f.sort_values(["sku_key", "wh_key", "date"]).reset_index(drop=True)
    fact_daily = f[["date_key", "sku_key", "wh_key", "demand_units", "sales_units", "lost_units", "receipts_units",
                    "orders_placed_units", "writeoff_units", "closing_stock_units", "stockout_flag"]].copy()

    # ---- fact_stock_snapshot_weekly (periodic snapshot grain: SKU x warehouse x week) ----
    f["week_index"] = ((f.date - d0).dt.days // 7).astype(int)
    f["week_start"] = d0 + pd.to_timedelta(f.week_index * 7, unit="D")
    g = f.groupby(["sku_key", "wh_key", "week_index"], sort=True)
    w = g.agg(week_start=("week_start", "first"), demand_units=("demand_units", "sum"), sales_units=("sales_units", "sum"),
              lost_units=("lost_units", "sum"), receipts_units=("receipts_units", "sum"),
              orders_placed_units=("orders_placed_units", "sum"), writeoff_units=("writeoff_units", "sum"),
              closing_stock_units=("closing_stock_units", "last"),      # semi-additive: take the LAST day, never sum over time
              stockout_days=("stockout_flag", "sum"), active_days=("date", "count")).reset_index()
    w["week_start_date_key"] = w.week_start.dt.strftime("%Y%m%d").astype(int)
    pr = w.sku_key.map(price)
    cs = w.sku_key.map(cost)
    w["demand_value_inr"] = w.demand_units * pr            # valued at selling price
    w["sales_value_inr"] = w.sales_units * pr
    w["lost_sales_value_inr"] = w.lost_units * pr
    w["cogs_value_inr"] = w.sales_units * cs              # valued at cost
    w["receipts_value_inr"] = w.receipts_units * cs
    w["writeoff_value_inr"] = w.writeoff_units * cs
    w["closing_stock_value_inr"] = w.closing_stock_units * cs
    fact_weekly = w.drop(columns=["week_start"])

    # ---- fact_purchase_order_line (accumulating snapshot: one row per PO line, milestones filled in over time) ----
    p = po.copy()
    p["sku_key"] = p.sku_id.map(kmap).astype(int)
    p["wh_key"] = p.wh_id.map(wmap).astype(int)
    p["supplier_key"] = p.supplier_id.map(smap).astype(int)
    for c_, n_ in [("order_date", "order_date_key"), ("promised_date", "promised_date_key"), ("received_date", "received_date_key")]:
        p[n_] = p[c_].dt.strftime("%Y%m%d")
        p[n_] = pd.to_numeric(p[n_], errors="coerce").astype("Int64")
    p["planned_lead_time_days"] = (p.promised_date - p.order_date).dt.days
    p["lead_time_days"] = (p.received_date - p.order_date).dt.days.astype("Int64")        # lag: order -> receipt
    p["days_late"] = (p.lead_time_days - p.planned_lead_time_days).astype("Int64")
    rec = p.received_date.notna()
    p["is_open"] = (~rec).astype(int)
    p["on_time_flag"] = np.where(rec, (p.lead_time_days <= p.planned_lead_time_days + 1).astype(float), np.nan)  # grace of 1 day
    p["in_full_flag"] = np.where(rec, (p.qty_received >= 0.98 * p.qty_ordered).astype(float), np.nan)
    p["otif_flag"] = np.where(rec, ((p.on_time_flag == 1) & (p.in_full_flag == 1)).astype(float), np.nan)
    p["po_value_inr"] = (p.qty_ordered * p.unit_price_inr).round(2)
    p["received_value_inr"] = (p.qty_received * p.unit_price_inr).round(2)
    fact_po = p[["po_line_id", "sku_key", "wh_key", "supplier_key", "order_date_key", "promised_date_key", "received_date_key",
                 "qty_ordered", "qty_received", "unit_price_inr", "po_value_inr", "received_value_inr", "planned_lead_time_days", "lead_time_days", "days_late",
                 "on_time_flag", "in_full_flag", "otif_flag", "is_open"]].copy()

    # ---- ABC class history (SCD Type 2) and XYZ (per SKU-location) ----
    sw = fact_weekly.assign(rev=fact_weekly.sales_value_inr)
    n_weeks = int(sw.week_index.max()) + 1
    snaps = []
    qend = [pd.Timestamp(x) for x in ["2025-06-30", "2025-09-30", "2025-12-31", "2026-03-31", "2026-06-30", "2026-09-30"]]
    for qe in qend + [d1]:
        wk_hi = int(((qe - d0).days) // 7)
        wk_hi = min(wk_hi, n_weeks - 1)
        lo = max(0, wk_hi - 51)
        if wk_hi < 3:
            continue
        rev = sw[(sw.week_index >= lo) & (sw.week_index <= wk_hi)].groupby("sku_key").rev.sum().reindex(dim_sku.sku_key).fillna(0)
        cls = abc_from_revenue(rev)
        snaps.append((qe if qe != d1 else d1, cls))
    hist = []
    cur = {}
    for sdate, cls in snaps:
        for k, c_ in cls.items():
            if k not in cur or cur[k]["abc_class"] != c_:
                if k in cur:
                    cur[k]["effective_to"] = (sdate - timedelta(days=1)).date()
                    cur[k]["is_current"] = 0
                    hist.append(cur[k])
                cur[k] = {"sku_key": k, "abc_class": c_, "effective_from": (d0 if k not in cur else sdate).date(), "effective_to": date(9999, 12, 31), "is_current": 1}
    hist.extend(cur.values())
    dim_class_hist = pd.DataFrame(hist).sort_values(["sku_key", "effective_from"]).reset_index(drop=True)
    abc_now = dim_class_hist[dim_class_hist.is_current == 1].set_index("sku_key").abc_class
    dim_sku["abc_class_current"] = dim_sku.sku_key.map(abc_now)

    last52 = fact_weekly[fact_weekly.week_index >= n_weeks - 52]
    st = last52.groupby(["sku_key", "wh_key"]).demand_units.agg(["mean", "std"])
    std0 = last52.groupby(["sku_key", "wh_key"]).demand_units.std(ddof=0)
    cvv = (std0 / st["mean"]).replace([np.inf], 9).fillna(9)
    xyz = pd.cut(cvv, [-1, 0.25, 0.5, 99], labels=["X", "Y", "Z"], right=False).astype(str)
    sku_loc_class = pd.DataFrame({"cv_weekly_52": cvv.round(4), "xyz_class": xyz}).reset_index()

    # ---- aggregate fact: category x warehouse x week (roll-up of the weekly snapshot) ----
    a = fact_weekly.merge(dim_sku[["sku_key", "category_id"]], on="sku_key")
    agg = a.groupby(["category_id", "wh_key", "week_index", "week_start_date_key"]).agg(
        demand_value_inr=("demand_value_inr", "sum"), sales_value_inr=("sales_value_inr", "sum"),
        lost_sales_value_inr=("lost_sales_value_inr", "sum"), cogs_value_inr=("cogs_value_inr", "sum"),
        receipts_value_inr=("receipts_value_inr", "sum"), writeoff_value_inr=("writeoff_value_inr", "sum"),
        closing_stock_value_inr=("closing_stock_value_inr", "sum"), stockout_days=("stockout_days", "sum"),
        active_days=("active_days", "sum")).reset_index()

    # ---- current position (as-of date): on-hand, on-order, ageing, expiry ----
    asof = d1
    pos = fact_daily[fact_daily.date_key == int(asof.strftime("%Y%m%d"))][["sku_key", "wh_key", "closing_stock_units"]].rename(
        columns={"closing_stock_units": "on_hand_units"})
    onord = fact_po[fact_po.is_open == 1].groupby(["sku_key", "wh_key"]).qty_ordered.sum().rename("on_order_units").reset_index()
    pos = pos.merge(onord, on=["sku_key", "wh_key"], how="left").fillna({"on_order_units": 0})
    b = bt.copy()
    b["sku_key"] = b.sku_id.map(kmap).astype(int)
    b["wh_key"] = b.wh_id.map(wmap).astype(int)
    b["age_days"] = (asof - b.received_date).dt.days
    b["age_bucket"] = pd.cut(b.age_days, [-1, 30, 60, 90, 10 ** 6], labels=["0-30", "31-60", "61-90", "90+"])
    shelf = dict(zip(dim_sku.sku_key, dim_sku.shelf_life_days))
    b["shelf_life_days"] = b.sku_key.map(shelf)
    b["days_to_expiry"] = np.where(b.shelf_life_days > 0, b.shelf_life_days - b.age_days, np.nan)
    pv = b.pivot_table(index=["sku_key", "wh_key"], columns="age_bucket", values="qty_on_hand", aggfunc="sum", observed=False).fillna(0)
    pv.columns = ["units_age_" + str(c).replace("-", "_").replace("+", "plus") for c in pv.columns]
    pos = pos.merge(pv.reset_index(), on=["sku_key", "wh_key"], how="left").fillna(0)
    for h in range(1, 9):
        e = b[(b.days_to_expiry <= h)].groupby(["sku_key", "wh_key"]).qty_on_hand.sum().rename(f"units_expiring_within_{h}d").reset_index()
        pos = pos.merge(e, on=["sku_key", "wh_key"], how="left").fillna({f"units_expiring_within_{h}d": 0})
    pos = pos.merge(sku_loc_class, on=["sku_key", "wh_key"], how="left")
    batches = b[["sku_key", "wh_key", "received_date", "qty_on_hand", "age_days", "age_bucket", "days_to_expiry"]].copy()

    print(f"  dim_date {len(dim_date):,} | dim_sku {len(dim_sku)} | dim_warehouse {len(dim_wh)} | dim_supplier {len(dim_sup)} | bridge {len(bridge)} | class history {len(dim_class_hist)} rows (SCD2)")
    print(f"  fact_stock_movement_daily {len(fact_daily):,} | fact_stock_snapshot_weekly {len(fact_weekly):,} | fact_purchase_order_line {len(fact_po):,} | aggregate fact {len(agg):,}")
    return dict(dim_date=dim_date, dim_sku=dim_sku, dim_warehouse=dim_wh, dim_supplier=dim_sup, bridge_sku_supplier=bridge, dim_sku_class_history=dim_class_hist,
                fact_stock_movement_daily=fact_daily, fact_stock_snapshot_weekly=fact_weekly, fact_purchase_order_line=fact_po,
                agg_weekly_category_warehouse=agg, current_position=pos, stock_batch_current=batches,
                sku_location_class=sku_loc_class), d0, d1


# ----------------------------------------------------------------------------------------
# 4. LOAD
# ----------------------------------------------------------------------------------------
def load(tables, out: Path):
    print("\n[4/5] LOAD  writing CSV files and the SQLite warehouse to", out)
    out.mkdir(parents=True, exist_ok=True)
    for name, df in tables.items():
        df.to_csv(out / f"{name}.csv", index=False)
    db = out / "inventory_dw.db"
    if db.exists():
        db.unlink()
    con = sqlite3.connect(db)
    for name, df in tables.items():
        d = df.copy()
        for c in d.columns:
            if str(d[c].dtype).startswith("datetime"):
                d[c] = d[c].dt.strftime("%Y-%m-%d")
            elif str(d[c].dtype) == "category":
                d[c] = d[c].astype(str)
        d.to_sql(name, con, index=False)
    idx = ["CREATE INDEX ix_fw ON fact_stock_snapshot_weekly(week_index, sku_key, wh_key)",
           "CREATE INDEX ix_fd ON fact_stock_movement_daily(date_key, sku_key, wh_key)",
           "CREATE INDEX ix_fp ON fact_purchase_order_line(supplier_key, received_date_key)",
           "CREATE INDEX ix_fps ON fact_purchase_order_line(sku_key, supplier_key)",
           "CREATE UNIQUE INDEX ux_bridge ON bridge_sku_supplier(sku_key, supplier_key)",
           "CREATE UNIQUE INDEX ux_date ON dim_date(date_key)"]
    for s in idx:
        con.execute(s)
    con.execute("""CREATE VIEW vw_weekly AS
        SELECT f.week_index, d.date AS week_start, d.fiscal_year, d.fiscal_quarter, d.month_name,
               s.sku_id, s.sku_name, s.category_id, s.category_name, s.abc_class_current AS abc_class,
               w.wh_id, w.wh_name, w.region, f.*
        FROM fact_stock_snapshot_weekly f
        JOIN dim_sku s ON s.sku_key = f.sku_key
        JOIN dim_warehouse w ON w.wh_key = f.wh_key
        JOIN dim_date d ON d.date_key = f.week_start_date_key""")
    con.commit()
    # referential integrity (facts -> dimensions)
    q = {"weekly -> dim_sku": "SELECT COUNT(*) FROM fact_stock_snapshot_weekly f LEFT JOIN dim_sku s USING(sku_key) WHERE s.sku_key IS NULL",
         "weekly -> dim_warehouse": "SELECT COUNT(*) FROM fact_stock_snapshot_weekly f LEFT JOIN dim_warehouse s USING(wh_key) WHERE s.wh_key IS NULL",
         "weekly -> dim_date": "SELECT COUNT(*) FROM fact_stock_snapshot_weekly f LEFT JOIN dim_date d ON d.date_key=f.week_start_date_key WHERE d.date_key IS NULL",
         "daily -> dim_date": "SELECT COUNT(*) FROM fact_stock_movement_daily f LEFT JOIN dim_date d USING(date_key) WHERE d.date_key IS NULL",
         "po -> dim_supplier": "SELECT COUNT(*) FROM fact_purchase_order_line f LEFT JOIN dim_supplier d USING(supplier_key) WHERE d.supplier_key IS NULL",
         "po -> bridge_sku_supplier": "SELECT COUNT(*) FROM fact_purchase_order_line f LEFT JOIN bridge_sku_supplier b ON b.sku_key=f.sku_key AND b.supplier_key=f.supplier_key WHERE b.sku_key IS NULL OR ABS(b.quoted_unit_price_inr-f.unit_price_inr)>0.000001",
         "bridge -> dim_sku / dim_supplier": "SELECT COUNT(*) FROM bridge_sku_supplier b LEFT JOIN dim_sku s USING(sku_key) LEFT JOIN dim_supplier d USING(supplier_key) WHERE s.sku_key IS NULL OR d.supplier_key IS NULL",
         "po -> dim_date (order)": "SELECT COUNT(*) FROM fact_purchase_order_line f LEFT JOIN dim_date d ON d.date_key=f.order_date_key WHERE d.date_key IS NULL"}
    ok = True
    for n, s in q.items():
        ok &= check(f"foreign key {n}", con.execute(s).fetchone()[0] == 0)
    d_sum = con.execute("SELECT SUM(sales_units), SUM(demand_units), SUM(receipts_units) FROM fact_stock_movement_daily").fetchone()
    w_sum = con.execute("SELECT SUM(sales_units), SUM(demand_units), SUM(receipts_units) FROM fact_stock_snapshot_weekly").fetchone()
    ok &= check("weekly snapshot reconciles to daily transactions (sales, demand, receipts)", d_sum == w_sum, f"{d_sum}")
    a_sum = con.execute("SELECT ROUND(SUM(sales_value_inr),2) FROM agg_weekly_category_warehouse").fetchone()[0]
    w2 = con.execute("SELECT ROUND(SUM(sales_value_inr),2) FROM fact_stock_snapshot_weekly").fetchone()[0]
    ok &= check("aggregate fact reconciles to detailed fact (sales value)", abs(a_sum - w2) < 0.5, f"{w2:,.0f}")
    con.close()
    return ok


# ----------------------------------------------------------------------------------------
# 5. SERVE: compact JSON for the dashboard
# ----------------------------------------------------------------------------------------
def serve(t, cat, wh, sup, sku, fest, d0, d1, web: Path):
    print("\n[5/5] SERVE  building web/data.json for the dashboard")
    web.mkdir(parents=True, exist_ok=True)
    W = int(t["fact_stock_snapshot_weekly"].week_index.max()) + 1
    ns, nw = len(sku), len(wh)
    C = ns * nw
    fw = t["fact_stock_snapshot_weekly"].sort_values(["sku_key", "wh_key", "week_index"])
    assert len(fw) == C * W
    arr = lambda col: fw[col].to_numpy().reshape(C, W)
    weekly = {"dem": arr("demand_units"), "sal": arr("sales_units"), "rcv": arr("receipts_units"), "ord": arr("orders_placed_units"),
              "wo": arr("writeoff_units"), "oh": arr("closing_stock_units"), "oos": arr("stockout_days"), "act": arr("active_days")}
    fd = t["fact_stock_movement_daily"].sort_values(["sku_key", "wh_key", "date_key"])
    D = len(fd) // C
    d90 = fd.demand_units.to_numpy().reshape(C, D)[:, -90:]
    pos = t["current_position"].sort_values(["sku_key", "wh_key"]).reset_index(drop=True)
    age = pos[["units_age_0_30", "units_age_31_60", "units_age_61_90", "units_age_90plus"]].to_numpy()
    expu = pos[[f"units_expiring_within_{h}d" for h in range(1, 9)]].to_numpy()
    p = t["fact_purchase_order_line"].copy()
    p = p.merge(t["dim_date"][["date_key", "date"]].rename(columns={"date_key": "order_date_key", "date": "od"}), on="order_date_key", how="left")
    p = p.merge(t["dim_date"][["date_key", "date"]].rename(columns={"date_key": "received_date_key", "date": "rd"}), on="received_date_key", how="left")
    off = lambda s: (s - d0).dt.days
    po = {"c": ((p.sku_key - 1) * nw + (p.wh_key - 1)).tolist(), "ord": off(p.od).tolist(),
          "recv": off(p.rd).fillna(-999).astype(int).tolist(), "qty": p.qty_ordered.tolist(), "got": p.qty_received.tolist(),
          "sup": (p.supplier_key - 1).tolist(), "planL": p.planned_lead_time_days.tolist()}
    br = t["bridge_sku_supplier"]
    terms = [[[int(r.supplier_key) - 1, float(r.quoted_unit_price_inr), int(r.quoted_lead_time_days), float(r.allocation_share), int(r.is_primary)]
              for r in br[br.sku_key == k].itertuples()] for k in range(1, ns + 1)]
    data = {
        "terms": terms,
        "meta": {"asof": d1.strftime("%Y-%m-%d"), "date0": d0.strftime("%Y-%m-%d"), "weeks": W, "days": D, "skus": ns, "warehouses": nw,
                 "generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"), "source": "data/raw -> etl/run_etl.py -> data/warehouse (star schema)"},
        "wh": [{"id": r.wh_id, "name": r.wh_name, "region": r.region, "size": r.size_index} for r in wh.itertuples()],
        "cats": [{"id": r.category_id, "name": r.category_name, "short": r.short_name, "shelf": int(r.shelf_life_days)} for r in cat.itertuples()],
        "sup": [{"id": i, "name": r.supplier_name, "short": r.short_name, "planL": float(r.planned_lead_time_days),
                 "planSd": float(r.planned_lead_time_sd_days)} for i, r in enumerate(sup.itertuples())],
        "skus": [{"code": r.sku_id, "name": r.sku_name, "cat": int(cat.index[cat.category_id == r.category_id][0]), "cost": int(r.unit_cost_inr),
                  "price": int(r.mrp_inr), "moq": int(r.moq_units), "pack": int(r.case_pack_units),
                  "sup": int(sup.index[sup.supplier_id == r.primary_supplier_id][0])} for r in sku.itertuples()],
        "fest": [{"n": r.festival, "d": r.date.strftime("%Y-%m-%d")} for r in fest.itertuples()],
        "weekly": {k: v.astype(int).ravel().tolist() for k, v in weekly.items()},
        "d90": d90.astype(int).ravel().tolist(),
        "fin": {"oh": pos.on_hand_units.astype(int).tolist(), "onOrd": pos.on_order_units.astype(int).tolist(),
                "age": age.astype(int).ravel().tolist(), "expU": expu.astype(int).ravel().tolist()},
        "po": po}
    path = web / "data.json"
    path.write_text(json.dumps(data, separators=(",", ":")))
    print(f"  wrote {path} ({path.stat().st_size/1e6:.2f} MB)")
    ok = check("data.json totals equal warehouse totals (sales units)", int(np.sum(weekly["sal"])) == int(t["fact_stock_snapshot_weekly"].sales_units.sum()))
    return ok


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--raw", default=str(ROOT / "data" / "raw"))
    ap.add_argument("--out", default=str(ROOT / "data" / "warehouse"))
    ap.add_argument("--web", default=str(ROOT / "web"))
    a = ap.parse_args()
    t0 = time.time()
    cat, wh, sup, sku, fest, mv, po, bt, terms = extract(Path(a.raw))
    if not validate_raw(cat, wh, sup, sku, mv, po, bt, terms):
        sys.exit("Source validation failed - ETL stopped (nothing was loaded).")
    tables, d0, d1 = transform(cat, wh, sup, sku, fest, mv, po, bt, terms)
    ok = load(tables, Path(a.out))
    ok &= serve(tables, cat, wh, sup, sku, fest, d0, d1, Path(a.web))
    rep = {"run_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"), "seconds": round(time.time() - t0, 1),
           "rows": {k: int(len(v)) for k, v in tables.items()}, "checks": CHECKS}
    (Path(a.out) / "etl_run_report.json").write_text(json.dumps(rep, indent=2))
    fails = [c for c in CHECKS if c["status"] == "FAIL"]
    print(f"\nDone in {time.time()-t0:.1f}s - {len(CHECKS)-len(fails)}/{len(CHECKS)} checks passed.")
    sys.exit(0 if ok and not fails else 1)


if __name__ == "__main__":
    main()
