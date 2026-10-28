# VIVA PREP — Inventory Control Tower (know this WITHOUT looking at the screen)

## 1. One-line answers
- **What is it?** An operational dashboard (Few's typology) with an analytical drill-down layer, interactive, batch-refreshed, for a regional FMCG distributor (6 warehouses, 120 SKUs, 80 weeks, Apr 2025–Oct 2026, FY Apr–Mar). Course typology: operational + analytical. It is both explanatory and exploratory.
- **Which ETL?** Custom Python/pandas **batch ETL** (`etl/run_etl.py`): Extract raw ERP/WMS CSVs → Validate (data-quality rules) → Transform (build dimensions, SCD2, facts, aggregates) → Load (star-schema CSVs + SQLite warehouse, FK/reconcile checks, 19 checks) → Serve (`web/data.json`). Source data comes from a seeded Node simulator standing in for ERP/WMS. Not Informatica/SSIS/Talend.
- **Backend?** None. Static HTML + D3.js reading data.json.
- **Without Claude, what frontend?** Power BI or Tableau (typical BI tools); or React + Recharts/Plotly; or Streamlit/Plotly Dash in Python.
- **Other tools:** D3.js 7.8.5, plain HTML/CSS/JS, IBM Plex fonts, Node.js, Python 3 (pandas, numpy), SQLite, Playwright (testing), Git/GitHub, WSL, Vercel. AI assistance (Claude) was used and permitted — be honest, and be able to explain everything.

## 2. Data model (Kimball)
- **Facts at three grains:** `fact_stock_movement_daily` (transaction), `fact_stock_snapshot_weekly` (periodic snapshot; closing stock is **semi-additive** — never sum across time, take last), `fact_purchase_order_line` (accumulating snapshot; lead-time lags, milestones fill in later). Plus an **aggregate fact** (week × category × warehouse) for speed.
- **Bridge table `bridge_sku_supplier`:** a product has 2–5 approved suppliers and a supplier serves many products (many-to-many) → bridge with a **weighting factor** (`allocation_share`) plus quoted price and lead time. Standard cost = primary's quote.
- **Dimensions (conformed, shared by facts):** date (fiscal Apr–Mar, festival windows), sku, warehouse, supplier. **SCD Type 2** for ABC class history and supplier planned lead time (new row when value changes, keeps history).
- **Fact constellation** (multiple facts sharing dimensions) → enables **drill-across**.
- Star vs snowflake: we use star (denormalised dims) for simple, fast queries.

## 3. OLAP examples in the dashboard
- **Drill-down:** All sites → warehouse → category → SKU (heatmap cell click + filters + exception row → SKU drawer). Time: Week → Month → Fiscal quarter → Fiscal year (Data check "group by").
- **Roll-up:** the "All sites"/"All" row/column of the heatmap; Data check by quarter/FY.
- **Slice:** one warehouse or category (fix one dimension). **Dice:** warehouse + category + ABC + date range together.
- **Drill-across:** SKU drawer from stock fact → PO lines/supplier (different fact); alert "Open supplier detail" jumps to Suppliers tab; stock vs sales vs PO.
- **Pivot:** ABC×XYZ matrix.

## 4. Chart-by-chart (what, why that chart, course link)
- **KPI strip (5 cards):** Inventory value, Fill rate, Days of inventory, Stock-out rate, Expiry write-offs. Each = big number + **bullet graph** (Few: compact, shows value vs target & bands, replaces gauges/speedometers) + **sparkline** (trend, no axes, Tufte). Delta vs prior period of equal length.
- **Heatmap (warehouse × category):** pattern-finding across 2 dimensions; colour diverging: orange = too little (stock-out risk), grey = on target, blue = too much (cash tied up). Measures switchable: Days of stock, Fill rate, Stock-out %, Aged >90d. Dairy target = half shelf life.
- **Ranked alerts:** action-oriented; sorted by ₹ at stake (Pareto thinking). Each has a link (drill-across).
- **Forecast vs actual line + lost-sales bars:** time series; dashed forecast = exponential smoothing α=0.3; shaded festival windows (Diwali, Holi, Dussehra); WAPE (error) and bias (+ = over-forecast).
- **Waterfall:** opening + received − sold(cost) − written off = closing; explains *why* value changed. Reconciles to ₹0 difference.
- **Supplier table / Suppliers tab:** OTIF % (number, coloured), quoted vs actual lead time, trend vs previous equal period. *Compare by product* ranks a SKU's 2–5 suppliers on price, speed, reliability (fit score, switchable weights) with a price × delivery map.
- **Exceptions table:** SKU-locations needing action: on-hand, cover, safety stock, reorder point, suggested order, ₹ at stake.
- **Pareto (ABC):** bars = revenue ranked, line = cumulative %, 70/90 thresholds → A/B/C. **ABC-XYZ matrix:** value × demand variability (CV).
- **Ageing, Turnover & GMROI, Bullwhip, Festival readiness:** remaining Analyse tabs (see formulas).
- **Why no pies/gauges:** Cleveland–McGill — humans compare position/length better than angle/area. Colour-blind safe palette (orange/blue/purple).

## 5. Formulas & terminology
- **Fill rate** = sales ÷ demand (₹ basis). **Stock-out rate** = zero-stock days ÷ active days (SKU-location). **Days of inventory (DOI)** = stock value ÷ avg daily COGS. **Turnover** = COGS ÷ avg inventory. **GMROI** = gross margin ÷ avg inventory cost.
- **Safety stock** = Z·√(L·σd² + d²·σL²). **ROP** = d·L + SS. **EOQ** = √(2DS/h) rounded to case pack, ≥ MoQ, capped 45 d (dairy: half shelf life). **Max level** = ROP + Q.
- **Z:** 90%=1.28, 95%=1.65, 97%=1.88, 98%=2.05, 99%=2.33.
- **ABC:** cumulative revenue 70% = A, next 20% = B, rest = C. **XYZ:** CV of weekly demand ≤0.25 = X, ≤0.5 = Y, else Z.
- **WAPE** = Σ|actual−forecast| ÷ Σactual. **Bias** = (Σforecast−Σactual) ÷ Σactual. **Bullwhip ratio** = variance of orders ÷ variance of demand (>1 = amplification). **OTIF** = on-time-in-full receipts ÷ receipts. **Lead time** = order → receipt. **Dead stock** = no sale in 90 days.
- **KPI vs metric; leading vs lagging; semi-additive; grain; conformed dimension; SCD1/2/3; surrogate key; ETL vs ELT; data mart vs warehouse; OLTP vs OLAP; snapshot types** — know definitions.
- **Indian context:** ₹ lakh/crore, Apr–Mar FY, festival demand, FSSAI shelf life.

## 6. Verifying numbers (sir's test)
Set start/end date → dates snap to whole Mon–Sun weeks (note under filters says "Weeks 68–80"). Flow measures (fill, stock-outs, write-offs, waterfall) use the range; stock value/DOI use the **end week**; alerts/ageing are "as of" latest date. Data check tab shows the same numbers; `verify_kpis.py` recomputes from SQL — tested identical on 6 range/filter combinations.

## 6b. Period vs As of, and are alerts predefined?
- Every card has a tag: **Period** (follows the chosen dates, whole weeks), **As of** (live position today, ignores dates), **Fixed** (Diwali 2025 vs 2026). Replenish has no date range because it is a live worklist.
- **Alerts are computed in the browser at run time** (`computeAlerts`) from the current filter selection, ranked by ₹ at stake: change a filter and they change. Thresholds are rules (e.g. lead time > plan×1.25+0.4 d), not stored text.
- Date picker only allows days with data (Apr 2025–Oct 2026). Drag the strip under the forecast to set the period. Dark mode and colour-blind mode (patterns) in the header. Pagers accept a page number + Enter.

## 7. Scenario questions (prepare answers)
- Stock-out in Beverages at Pune but excess at Hyderabad? → rebalance/transfer between warehouses; drill heatmap → SKU → drawer.
- Fill rate high but stock-outs exist? → ₹-weighted vs day-count; A-items fine, C-items out.
- Supplier lead time rose 4→7.6 d? → reorder point stale, raise SS, change Settings, expect more safe stock (cost trade-off).
- Diwali in 21 days? → Festival readiness tab: pre-build stock; forecast reacts late (smoothing lag).
- Why is DOI high but stock-outs too? → wrong mix (excess in some SKUs, shortage in others); averages hide.
- What if data refreshes? → rerun ETL (batch), dashboard reads new data.json.
- Limitations: data simulated; festival uplift & lead times are assumptions; no real-time; single currency; forecast is simple.
- Benchmark: global out-of-stock ≈ 8.3% (Gruen–Corsten); vendor stats are weaker evidence.

## 8. Ownership statement
We designed the data model, formulas and layout, ran ETL and tested reconciliation; AI was used as a coding assistant as permitted. Each member can explain every part.
