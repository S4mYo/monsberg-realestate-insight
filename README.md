# US Metro Real Estate Investment Insight

An end-to-end data engineering and analytics project that scores and ranks the 50 largest US metro areas on real estate investment attractiveness — from raw public data through a Python ETL pipeline, a Postgres star schema, an XGBoost forecasting model with confidence intervals, and an interactive Power BI dashboard with neighborhood-level drill-down, fully automated on a monthly/annual cadence and covered by a CI-tested pipeline.

**[View the live dashboard →](https://app.powerbi.com/view?r=eyJrIjoiMDkzODk5ZTQtYjQxZC00MzFhLWEwZjMtZTU3YmViZTQzMjlhIiwidCI6ImNlMzE0NzhkLTZlN2EtNGNlNy04NjcwLWE1YjlkNTE4ODRmOSIsImMiOjh9)**

Built by [Samuel Pollák](https://github.com/S4mYo) — Data Science student (Finance & Economics).

---

## The business question

*Which US metro markets currently offer the best risk-adjusted real estate investment opportunity — and once you've picked one, which neighborhoods within it look strongest?*

Answering this well means combining four things that no single public dataset provides together: how fast prices are actually moving, how much a property would yield in rent, how affordable financing is right now, and whether the underlying population is growing or shrinking. This project builds a pipeline that pulls all four, keeps them updated automatically, and turns them into a single ranked scorecard — plus a 12-month price forecast (with an honest, widening confidence band) to sanity-check the ranking, and a neighborhood-level view for drilling into any one metro.

---

## Dashboard

**Overview** — a ranked scorecard across all 50 metros, a map colored by investment score, a Top 10 chart, and quick-filter bookmarks (Most Affordable, Top 10, historical year comparisons).

![Overview page](docs/overview.png)

**Metro Detail** (drill-through) — click any metro on the Overview page to open its dedicated view: full price/rent history, population migration by year, and a trend indicator against a zero-growth goal. A bookmark-toggled chart switches between the full historical price line and a 12-month forecast with a widening confidence interval.

![Metro Detail page](docs/metro-detail.png)

**Street Overview** (drill-through from Metro Detail) — zooms into a single metro's neighborhoods: a map colored by year-over-year price growth, best/weakest-performing neighborhood callouts, and a top-5 price trend chart.

![Street Overview page](docs/street-overview.png)

---

## Architecture

```
Zillow (ZHVI, ZORI,   ─┐
  neighborhood ZHVI)   │
FRED (mortgage rate,  ─┼─▶  Python ETL  ─▶  Postgres (Neon)  ─▶  Power BI  ─▶  Published report
  Case-Shiller)        │      scripts        star/galaxy         DAX model
Census Bureau (pop.)  ─┘                       schema
                                  │
                                  ▼
                         XGBoost forecast
                    (12-month recursive, with
                     widening confidence bands)
                                  │
                                  ▼
                          GitHub Actions
                (tests on every push + monthly/annual cron)
```

Four independent public data sources are extracted, cleaned, and loaded into a relational schema; a forecasting model reads from that schema and writes its own predictions (plus uncertainty bounds) back into it; Power BI connects directly to the database and does all scoring, ranking, and visualization in DAX; GitHub Actions runs the test suite on every push and re-runs the whole data pipeline on a schedule with no manual intervention.

---

## Data sources

| Source | What | Granularity | Update cadence |
|---|---|---|---|
| [Zillow Research](https://www.zillow.com/research/data/) | ZHVI (home value index), ZORI (rent index) | Monthly, per metro | Published ~16th of each month |
| [Zillow Research](https://www.zillow.com/research/data/) | Neighborhood-level ZHVI | Monthly, per neighborhood | Same monthly release |
| [FRED](https://fred.stlouisfed.org/) | 30-year mortgage rate, Case-Shiller national home price index | Weekly / monthly, national | Mortgage rate weekly; Case-Shiller last Tuesday of the month, ~2-month lag |
| [US Census Bureau](https://www.census.gov/programs-surveys/popest.html) | Metro population estimates, net migration | Annual, per metro | New vintage released ~March, for the year ending the prior July |

All four are free, public datasets, pulled directly via their APIs or public CSV endpoints — no scraping, no paid data.

The 50-metro roster is fixed at initialization (top 50 US metros by Zillow's `SizeRank`) and reused as the join key across every other source, since Census and Zillow name and code metros differently — matching them required a custom crosswalk (`derive_zillow_style_name`, in [`db.py`](scripts/db.py)), shared between the Census and neighborhood-level pipelines since both face the same long-form-metro-name problem.

**Note on neighborhood-level ZORI:** Zillow does not publish a rent index at the neighborhood level (only metro and ZIP code), so the Street Overview page shows price momentum only — no neighborhood-level rental yield. See *Possible extensions*.

---

## Data model

Postgres schema follows a star/galaxy pattern: one shared metro dimension, several fact tables at different grains, a national-only fact table with no metro dimension, and a second dimension/fact pair one level down in granularity.

```
dim_metro ──┬── fact_home_values          (metro, month, home_type → ZHVI)
            ├── fact_rent                 (metro, month → ZORI)
            ├── fact_population           (metro, year → population, net_migration)
            ├── fact_forecast             (metro, forecast_month → predicted ZHVI, lower/upper bound)
            └── dim_neighborhood ── fact_neighborhood_home_values  (neighborhood, month → ZHVI)

fact_macro  (month → mortgage_rate_30y, case_shiller_index)   [no metro_id]
```

`fact_macro` has no metro dimension because mortgage rates and the Case-Shiller index are national, not metro-level — collapsing that into a per-metro fact table would mean duplicating a national number 50 times over.

`dim_neighborhood` is keyed on `(zillow_region_name, city, metro_id)`, not just `(zillow_region_name, metro_id)` — a single metro area can span multiple independent cities (e.g. the "New York, NY" metro includes Mount Vernon), and two of those cities can each independently have a neighborhood with the same name. It also carries a `size_rank_within_metro` column (see *Street-level neighborhood analysis* below).

See [`sql/schema.sql`](sql/schema.sql) for full DDL and column-level comments.

---

## ETL pipeline

Six Python scripts, each independently runnable and safe to re-run without duplicating data:

- **`fetch_zhvi.py`** / **`fetch_zori.py`** — download Zillow's public metro-level CSVs, reshape wide-format (one column per month) into long format, and insert only rows not already present.
- **`fetch_zhvi_neighborhood.py`** — same pattern, one level down in granularity. Two Zillow-specific wrinkles handled here: (1) Zillow occasionally publishes two separate `RegionID`s for what looks like the same neighborhood name (e.g. after redefining boundaries) — resolved by keeping only the lower-`SizeRank` ("more primary") record per name; (2) Zillow's own `SizeRank` is global across all US regions, so it isn't comparable between a large metro (where even a modest neighborhood ranks in the thousands) and a small one — a `size_rank_within_metro` column re-ranks neighborhoods relative only to others in the same metro.
- **`fetch_fred.py`** — pulls both FRED series via their REST API, aligns weekly mortgage data to month-end averages, and inner-joins with Case-Shiller (which lags ~2-3 months) so incomplete months are dropped rather than loaded with gaps.
- **`fetch_census.py`** — downloads the latest Census population vintage. The target URL encodes the vintage year, and Census has no live API for current-year estimates, so the script probes candidate URLs (this year, last year, two years back) with a `HEAD` request and uses the first one that resolves — no hardcoded year to go stale.
- **`forecast.py`** — trains the model, evaluates it against baselines, and writes both point predictions and confidence bounds (see below). Skips retraining entirely if no new price data has arrived since the last run, so a monthly automation run that finds nothing new doesn't burn compute for no reason.

Every load function uses one of two safe-to-repeat patterns: an `UPDATE` for values that get overwritten in place (like a metro's CBSA code), or an "insert only what's not already there" pattern (comparing incoming rows against what's in the table via a `pandas` merge) for values that accumulate over time (a new month of prices, a new year of population data). The neighborhood-level fact table's bulk upsert (3.6M+ rows) uses chunked, multi-row inserts (`chunksize=10000, method="multi"`) rather than one statement per row.

---

## Testing & CI

21 unit tests (`pytest tests/ -v`) covering the logic most at risk of silent breakage — not database calls or network I/O, but pure functions extracted specifically to be testable in isolation:

- Metro name crosswalk (`derive_zillow_style_name`) — hyphenated/multi-state names, slash separators, edge cases like `Albany-Schenectady-Troy`.
- Duplicate-neighborhood resolution (`keep_primary_region_per_name`) — the two-`RegionID`-per-name problem described above.
- Forecast feature engineering (`add_lag_features`) — lag windows never cross a metro boundary.
- Recursive forecast mechanics — correct row count, correct price compounding, confidence interval widens with horizon and always contains the point prediction.
- Forecast staleness check (`is_forecast_stale`) — decides whether a re-run is needed, without touching the database.
- Upsert logic (`get_new_rows`) — the shared "what's actually new" comparison every fetch script relies on.

**`.github/workflows/tests.yml`** runs the full suite on every push and pull request to `main`, no secrets required. A separate **`monthly_update.yml`** workflow (see *Automation*) runs the actual data pipeline on a schedule.

---

## Forecasting model

**Goal:** predict each metro's home value index 12 months ahead, with an honest measure of how much to trust each step.

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

**Confidence intervals:** because prediction is recursive, uncertainty compounds — a real, mild slowdown in the most recent actual data gets extrapolated forward, and errors from each step feed into the next. Rather than presenting month 1 and month 12 with equal implied certainty, each step's bound widens as `margin = Z × MAE × √step` (`Z ≈ 1.28`, an ~80% interval) — the standard result for compounding, roughly independent errors across recursive steps. Month 1 ships with a tight band; month 12 with a visibly wider one. This is a property of recursive forecasting itself (any model doing 12-step recursive prediction faces the same compounding, not something a different algorithm would sidestep), so widening the interval — rather than pretending the model is equally sure the whole way out — is the honest fix.

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

## Street-level neighborhood analysis

Drilling from a metro into its neighborhoods surfaced two problems that don't show up at metro level, worth documenting because the fixes generalize.

**Filtering scope:** the page filters by the neighborhood's full metro (`metro_id`), not just its literal city name. US metro definitions are often wider than the core city — "Philadelphia" metro includes parts of Delaware, "Miami" metro includes over 40 separate cities from Fort Lauderdale to West Palm Beach. Filtering to city name alone made large multi-city metros look sparse (Miami showed 36 neighborhoods instead of 911); filtering to the full metro is the more complete, correct picture once the geocoding problem below was solved.

**Geocoding reliability:** Bing/Azure's map visual geocodes from free text, and a handful of neighborhood names — real, correctly-labeled Zillow data — are ambiguous enough to be placed in the wrong location: names shared with better-known places elsewhere (e.g. "Silver Lake" also exists, more prominently, in Los Angeles) or names that read as standalone cities in their own right (e.g. "Grant City," a real Staten Island neighborhood). Two fixes, in order of impact:
1. **Structured map labels** — instead of a flat `"{name}, {city}, {state}"` string, the label explicitly states the hierarchy: `"{name} (neighborhood in {city}), {state}, United States"`. This resolved the large majority of misplacements by giving the geocoder an unambiguous relationship instead of a flat list of tokens it had to disambiguate itself.
2. **A small explicit exclusion list** — a handful of very obscure neighborhoods (Bing appears to have no record of them at all, rather than picking the wrong match) are filtered out by name on the map visual. This is a visualization-layer filter only; the underlying data is untouched.

**Prominence filtering:** to keep the map both legible and reliably geocodable, it's filtered to each metro's top neighborhoods by `size_rank_within_metro` — obscure, low-`SizeRank` neighborhoods are exactly the ones most likely to have no Bing geocoding record at all.

---

## Automation

Two GitHub Actions workflows for data, plus one for tests, all re-runnable manually:

- **`tests.yml`** — runs the full pytest suite on every push/PR to `main`.
- **`monthly_update.yml`** (18th of each month) — Zillow (metro + neighborhood ZHVI), ZORI, FRED, and forecast, in that order.
- **`annual_census_update.yml`** (28th of March, with a fallback run in April) — Census population data.

Both data workflows use the same idempotent load patterns described above, so a run that finds nothing new is a no-op, not a risk. Secrets (`DATABASE_URL`, `FRED_API_KEY`) are stored as GitHub Actions repository secrets, never committed.

---

## Tech stack

**Data & ML:** Python, pandas, SQLAlchemy, XGBoost, scikit-learn
**Testing:** pytest
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

Run the schema in `sql/schema.sql` against your Postgres instance, then, from the project root:
```bash
python -m scripts.fetch_zhvi
python -m scripts.fetch_zhvi_neighborhood
python -m scripts.fetch_zori
python -m scripts.fetch_fred
python -m scripts.fetch_census
python -m scripts.forecast
```

Run the test suite with:
```bash
pytest tests/ -v
```

Connect Power BI Desktop to the same database to explore or rebuild the report.

---

## Possible extensions

- **Neighborhood-level rental yield** — Zillow doesn't publish ZORI below ZIP code, so projecting yield at neighborhood granularity would need a separate ZIP-based rent pipeline plus a geographic ZIP↔neighborhood crosswalk (the two aren't 1:1 — a ZIP code can span parts of several neighborhoods and vice versa).
- **True neighborhood boundaries** — the map currently plots each neighborhood as a single geocoded point, not its actual shape. Real boundary polygons would need a separate GeoJSON source and a shape-map visual, not the point-based map used here.
- **A second drill-through level** — from Street Overview into an individual neighborhood's own detail page, mirroring the Overview → Metro Detail pattern one level deeper.
- **Rent forecasting** — the forecast model currently predicts ZHVI only. Extending it to ZORI would need its own training pipeline and would let `Rental Yield` be projected forward, not just computed from current data — but combining two independently-uncertain forecasts adds compounding error worth thinking through carefully first.
- **Model versioning** — `fact_forecast` currently keeps only the latest forecast; a `model_version`-based history would allow tracking forecast accuracy over time.
