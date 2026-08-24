# US Metro Real Estate Investment Insight

An end-to-end data engineering and analytics project that scores and ranks the 50 largest US metro areas on real estate investment attractiveness — from raw public data through a Python ETL pipeline, a Postgres star schema, an XGBoost forecasting model, and an interactive Power BI dashboard, fully automated on a monthly/annual cadence.

**[View the live dashboard →](https://app.powerbi.com/view?r=eyJrIjoiODM4ZmI0OTMtYTFkOS00NmY5LTk1MjMtMDE0NzdlZmI4NDIzIiwidCI6ImNlMzE0NzhkLTZlN2EtNGNlNy04NjcwLWE1YjlkNTE4ODRmOSIsImMiOjh9)**

Built by [Samuel Pollák](https://github.com/S4mYo) — Data Science student (Finance & Economics).

---

## The business question

*Which US metro markets currently offer the best risk-adjusted real estate investment opportunity?*

Answering this well means combining four things that no single public dataset provides together: how fast prices are actually moving, how much a property would yield in rent, how affordable financing is right now, and whether the underlying population is growing or shrinking. This project builds a pipeline that pulls all four, keeps them updated automatically, and turns them into a single ranked scorecard — plus a 12-month price forecast to sanity-check the ranking against where the model thinks the market is headed.

---

## Dashboard

**Overview** — a ranked scorecard across all 50 metros, a map colored by investment score, a Top 10 chart, and quick-filter bookmarks (Most Affordable, Top 10, historical year comparisons).

![Overview page](docs/overview.png)

**Metro Detail** (drill-through) — click any metro on the Overview page to open its dedicated view: full price/rent history, population migration by year, and a trend indicator against a zero-growth goal.

![Metro Detail page](docs/metro-detail.png)

---

## Architecture

```
Zillow (ZHVI, ZORI)  ─┐
FRED (mortgage rate,  ─┼─▶  Python ETL  ─▶  Postgres (Neon)  ─▶  Power BI  ─▶  Published report
  Case-Shiller)        │      scripts        star/galaxy         DAX model
Census Bureau (pop.)  ─┘                       schema
                                  │
                                  ▼
                         XGBoost forecast
                        (12-month recursive)
                                  │
                                  ▼
                          GitHub Actions
                     (monthly + annual cron)
```

Four independent public data sources are extracted, cleaned, and loaded into a relational schema; a forecasting model reads from that schema and writes its own predictions back into it; Power BI connects directly to the database and does all scoring, ranking, and visualization in DAX; GitHub Actions re-runs the whole pipeline on a schedule with no manual intervention.

---

## Data sources

| Source | What | Granularity | Update cadence |
|---|---|---|---|
| [Zillow Research](https://www.zillow.com/research/data/) | ZHVI (home value index), ZORI (rent index) | Monthly, per metro | Published ~16th of each month |
| [FRED](https://fred.stlouisfed.org/) | 30-year mortgage rate, Case-Shiller national home price index | Weekly / monthly, national | Mortgage rate weekly; Case-Shiller last Tuesday of the month, ~2-month lag |
| [US Census Bureau](https://www.census.gov/programs-surveys/popest.html) | Metro population estimates, net migration | Annual, per metro | New vintage released ~March, for the year ending the prior July |

All four are free, public datasets, pulled directly via their APIs or public CSV endpoints — no scraping, no paid data.

The 50-metro roster is fixed at initialization (top 50 US metros by Zillow's `SizeRank`) and reused as the join key across every other source, since Census and Zillow name and code metros differently — matching them required a custom crosswalk (see [`fetch_census.py`](scripts/fetch_census.py)).

---

## Data model

Postgres schema follows a star/galaxy pattern: one shared dimension (`dim_metro`), several fact tables at different grains, and one fact table (`fact_macro`) that deliberately has **no** metro dimension because mortgage rates and the Case-Shiller index are national, not metro-level — collapsing that into a per-metro fact table would mean duplicating a national number 50 times over.

```
dim_metro ──┬── fact_home_values   (metro, month, home_type → ZHVI)
            ├── fact_rent          (metro, month → ZORI)
            ├── fact_population    (metro, year → population, net_migration)
            └── fact_forecast      (metro, forecast_month → predicted ZHVI)

fact_macro  (month → mortgage_rate_30y, case_shiller_index)   [no metro_id]
```

See [`sql/schema.sql`](sql/schema.sql) for full DDL.

---

## ETL pipeline

Five Python scripts, each independently runnable and safe to re-run without duplicating data:

- **`fetch_zhvi.py`** / **`fetch_zori.py`** — download Zillow's public CSVs, reshape wide-format (one column per month) into long format, and insert only rows not already present.
- **`fetch_fred.py`** — pulls both FRED series via their REST API, aligns weekly mortgage data to month-end averages, and inner-joins with Case-Shiller (which lags ~2-3 months) so incomplete months are dropped rather than loaded with gaps.
- **`fetch_census.py`** — downloads the latest Census population vintage. The target URL encodes the vintage year, and Census has no live API for current-year estimates, so the script probes candidate URLs (this year, last year, two years back) with a `HEAD` request and uses the first one that resolves — no hardcoded year to go stale.
- **`forecast.py`** — trains the model and writes predictions (see below). Skips retraining entirely if no new price data has arrived since the last run, so a monthly automation run that finds nothing new doesn't burn compute for no reason.

Every load function uses one of two safe-to-repeat patterns: an `UPDATE` for values that get overwritten in place (like a metro's CBSA code), or an "insert only what's not already there" pattern (comparing incoming rows against what's in the table via a `pandas` merge) for values that accumulate over time (a new month of prices, a new year of population data).

---

## Forecasting model

**Goal:** predict each metro's home value index 12 months ahead.

**Approach:** one pooled XGBoost regressor across all 50 metros (metro ID as a categorical feature), predicting **month-over-month percent change** rather than the raw price — a tree model can't extrapolate beyond the value range it was trained on, and ZHVI only ever trends upward historically, so a raw-price target would eventually fall outside that range. Percent change stays in a stable, recurring band instead.

**Features:** each metro's own price history (1, 3, 6, and 12-month lagged percent changes) plus calendar month, to capture seasonality. Macro variables (mortgage rate, Case-Shiller) are deliberately excluded — using them would require forecasting *them* too, and next month's mortgage rate isn't known at prediction time.

**Prediction:** recursive — the model predicts one month, that prediction becomes a lag input for the next month, twelve times per metro. Predicted prices compound from the last known real price.

**Backtest** (chronological train/test split, last 12 months held out):

| | MAE (pct. points) |
|---|---|
| Model | 0.00111 |
| Baseline: always predict 0% change | 0.00249 |
| Baseline: predict last month repeats | 0.00116 |

The model modestly beats the naive "last month repeats" baseline — real momentum in home prices makes that a genuinely hard baseline to clear, so a small, consistent edge is an honest result rather than a weak one.

**A limitation worth stating plainly:** because the prediction is recursive, a real, mild slowdown observed in the most recent months of actual data gets extrapolated forward for the full 12-month horizon. The model is reflecting a genuine recent trend, not malfunctioning — but it implicitly assumes that trend continues linearly, which tends to understate how often real markets stabilize or reverse over a full year. This is a property of recursive forecasting itself, not something a different algorithm (LSTM, transformer, etc.) would avoid — any model doing 12-step recursive prediction faces the same compounding. A useful next step would be a widening confidence interval per forecast step, rather than presenting month 1 and month 12 with equal implied certainty.

---

## Investment score

Four components, each converted to a 1–50 rank across metros (so a $2M market and a 3% market can be combined on the same scale), then combined with fixed weights and rescaled to 0–100:

| Component | What it measures | Weight | Direction |
|---|---|---|---|
| Momentum | YoY ZHVI growth | 30% | Higher is better |
| Yield | Annualized rent ÷ price | 30% | Higher is better |
| Affordability | Est. monthly mortgage payment (20% down, 30yr) | 25% | Lower is better |
| Population | YoY population growth | 15% | Higher is better |

Momentum and yield carry the most weight because they're direct, realized financial signals — price growth and rental income that have actually happened. Population growth is weighted lower because it's a leading indicator, not a financial outcome by itself: it's a useful confirming signal (does momentum look demographically grounded, not just speculative?) rather than something that alone justifies a high score.

A separate `Expected 12M Appreciation` figure (from the forecast model) is shown alongside the score but deliberately **not** folded into it — it's downstream of the same price momentum the score already captures, so including it would double-count that signal.

---

## Automation

Two GitHub Actions workflows, both re-runnable manually and scheduled to run a few days after each source's typical release date:

- **`monthly_update.yml`** (18th of each month) — Zillow, FRED, and forecast, in that order.
- **`annual_census_update.yml`** (28th of March, with a fallback run in April) — Census population data.

Both use the same idempotent load patterns described above, so a run that finds nothing new is a no-op, not a risk. Secrets (`DATABASE_URL`, `FRED_API_KEY`) are stored as GitHub Actions repository secrets, never committed.

---

## Tech stack

**Data & ML:** Python, pandas, SQLAlchemy, XGBoost, scikit-learn
**Database:** PostgreSQL (Neon — serverless, auto-resumes on connection)
**BI:** Power BI Desktop, DAX
**Automation:** GitHub Actions
**Version control:** Git / GitHub

---

## Running it locally

```bash
git clone https://github.com/S4mYo/monsberg-realestate-insight.git
cd monsberg-realestate-insight
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

Create a `.env` file with:
```
DATABASE_URL=postgresql://user:password@host/db?sslmode=require
FRED_API_KEY=your_fred_api_key
CENSUS_API_KEY=your_census_api_key
```

Run the schema in `sql/schema.sql` against your Postgres instance, then:
```bash
python scripts/fetch_zhvi.py
python scripts/fetch_zori.py
python scripts/fetch_fred.py
python scripts/fetch_census.py
python scripts/forecast.py
```

Connect Power BI Desktop to the same database to explore or rebuild the report.

---

## Possible extensions

- **Neighborhood/ZIP-level detail** — current scope is metro-level only; Zillow and Census both publish more granular data that could support drill-through below the metro level.
- **Forecast uncertainty bands** — widening confidence intervals per forecast step, to make the 12-month horizon's declining certainty visible rather than implicit.
- **Model versioning** — `fact_forecast` currently keeps only the latest forecast; a `model_version`-based history would allow tracking forecast accuracy over time.
