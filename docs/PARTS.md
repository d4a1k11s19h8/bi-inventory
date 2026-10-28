# Division of parts (4 equal parts, ~4–5 min each; whole viva 18–20 min, dashboard only)
Everyone must know the WHOLE dashboard, ETL and terminology (see VIVA_PREP.md). Any member can be asked anything.

| Part | Who | Covers |
|---|---|---|
| 1 Intro | **Arjun** | Business problem (FMCG distributor, 6 warehouses, 120 SKUs); dashboard type; architecture + ETL; star schema; tools |
| 2 Control panel | **Daksh** | Date range & filters (slice/dice), KPI strip (bullet graphs, sparklines), Data check tab & verification |
| 3 Diagnose | **Bhumika** | Heatmap (drill-down), ranked alerts, forecast chart, waterfall, SKU drawer workings |
| 4 Analyse & close | **Shravya** | Analyse tabs (ABC-XYZ, ageing, turnover/GMROI, bullwhip, festival), Suppliers, Settings, conclusion |
(Swap names freely — the split is by section, not by person.)

## Problems faced (be honest, own it)
- Arjun: moving from an in-browser simulation to a real ETL so "what ETL?" has a true answer; reconciling ETL vs dashboard (25 checks).
- Daksh: date snapping to whole weeks; KPIs for a range vs. end-of-week stock; 0- vs 1-based week labels.
- Bhumika: calibrating data so the heatmap is meaningful (dairy shelf-life target, write-offs absurd at first); label overlap on forecast chart.
- Shravya: XYZ thresholds not discriminating; supplier lead-time vs planned (SCD2); colour contrast in dark/light.
Word-for-word scripts: after the team approves the dashboard.
