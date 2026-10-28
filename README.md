# Inventory Control Tower — CSL430 BI & Analytics (VNIT Nagpur)
Group: BT23CSE006 Bhumika Ujjainkar · BT23CSE015 Arjun Jaishankar · BT23CSE039 Daksh Rathore · BT23CSE056 Puram Shravya
All data is **simulated** for academic demonstration.

🚀 **Live Dashboard:** [https://d4a1k11s19h8.github.io/bi-inventory/](https://d4a1k11s19h8.github.io/bi-inventory/)

## Pipeline
`tools/simulate_source.js` (ERP/WMS stand-in) → `data/raw/*.csv` → `etl/run_etl.py` (extract → validate → transform → load → serve) → `data/warehouse/*.csv` + `inventory_dw.db` (star schema) → `web/data.json` → `web/index.html` (static HTML + D3, no backend).

## Setup on WSL (Ubuntu) — run in order
```bash
mkdir -p ~/bi-inventory && cd ~/bi-inventory        # then copy/unzip the project files here
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
node tools/simulate_source.js data/raw               # optional: regenerate raw CSVs (needs Node)
python etl/run_etl.py                                # expect: 25/25 checks passed
python etl/verify_kpis.py --from 2026-07-20 --to 2026-10-18          # SQL recompute of KPIs
python etl/verify_kpis.py --from 2026-07-20 --to 2026-10-18 --wh NGP --cat OIL --sup   # --sup adds the supplier scorecard
cd web && python -m http.server 8765                 # open http://localhost:8765
```
Note: open the dashboard via the server (it fetches `data.json`), not by double-clicking the file.

## Verify the dashboard like sir does
Pick a From/To date on the dashboard (it snaps to whole Mon–Sun weeks), open **Data check**, and compare with `verify_kpis.py` run on the same dates/filters (`--wh`, `--cat`, `--abc`). Numbers must match (the Data check table also has a *Supplier receipts* row: lines, OTIF, lead time, spend).

## Sourcing model
Each SKU has 2–5 approved suppliers (`sku_supplier_terms.csv` → `bridge_sku_supplier`, many-to-many, with allocation share, quoted price and quoted lead time). Standard cost = primary supplier's quote; faster suppliers charge more. POs are split by share; planning uses the share-weighted blended lead time. Dashboard: Suppliers → *Compare by product* (e.g. Basmati Rice 1 kg, 5 suppliers).

## GitHub + Vercel
```bash
git init && git add . && git commit -m "Inventory dashboard"
git branch -M main
git remote add origin https://github.com/<your-user>/bi-inventory.git
git push -u origin main
```
Vercel: vercel.com → Add New Project → import the repo → Framework "Other" → deploy (`vercel.json` serves the `web/` folder). Or: `npx vercel --prod`.
Docs: `docs/VIVA_PREP.md`, `docs/PARTS.md`.
