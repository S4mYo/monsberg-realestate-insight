-- ============================================
-- dim_metro: list of metro areas (Zillow <-> Census crosswalk)
-- One row = one metro area. Shared dimension across all fact tables.
-- ============================================
CREATE TABLE dim_metro (
    metro_id SERIAL PRIMARY KEY,
    zillow_region_name TEXT UNIQUE NOT NULL,
    census_cbsa_code TEXT,
    state TEXT
);

COMMENT ON TABLE dim_metro IS 'Crosswalk between Zillow and Census metro identifiers. Shared (conformed) dimension.';
COMMENT ON COLUMN dim_metro.zillow_region_name IS 'Exact region name as used in Zillow Research CSV exports.';
COMMENT ON COLUMN dim_metro.census_cbsa_code IS 'Core-Based Statistical Area code from the Census Bureau.';

-- ============================================
-- fact_home_values: monthly home prices (ZHVI)
-- Grain: one row = one metro + one month + one home type
-- Source: Zillow Research, updated monthly
-- ============================================
CREATE TABLE fact_home_values (
    metro_id INT REFERENCES dim_metro(metro_id),
    date DATE NOT NULL,
    home_type TEXT NOT NULL,
    zhvi_value NUMERIC,
    PRIMARY KEY (metro_id, date, home_type)
);

COMMENT ON TABLE fact_home_values IS 'Zillow Home Value Index — monthly, refreshed via GitHub Actions.';
COMMENT ON COLUMN fact_home_values.home_type IS 'Property type segment, e.g. all_homes, sfr, condo.';
COMMENT ON COLUMN fact_home_values.zhvi_value IS 'Typical home value in USD, smoothed and seasonally adjusted.';

-- ============================================
-- fact_rent: monthly rent index (ZORI)
-- Grain: one row = one metro + one month
-- Source: Zillow Research, updated monthly
-- ============================================
CREATE TABLE fact_rent (
    metro_id INT REFERENCES dim_metro(metro_id),
    date DATE NOT NULL,
    zori_value NUMERIC,
    PRIMARY KEY (metro_id, date)
);

COMMENT ON TABLE fact_rent IS 'Zillow Observed Rent Index — monthly, refreshed via GitHub Actions.';
COMMENT ON COLUMN fact_rent.zori_value IS 'Typical observed market-rate rent in USD.';

-- ============================================
-- fact_population: annual population estimates
-- Grain: one row = one metro + one year
-- Source: US Census Bureau (PEP), updated annually
-- ============================================
CREATE TABLE fact_population (
    metro_id INT REFERENCES dim_metro(metro_id),
    year INT NOT NULL,
    population BIGINT,
    net_migration INT,
    PRIMARY KEY (metro_id, year)
);

COMMENT ON TABLE fact_population IS 'Census Bureau Population Estimates Program — annual, refreshed via a separate low-frequency job.';
COMMENT ON COLUMN fact_population.net_migration IS 'Net migration for the year (in + out), a leading demand signal.';

-- ============================================
-- fact_macro: national-level monthly macro indicators
-- Grain: one row = one month (no metro breakdown)
-- Source: FRED, updated monthly
-- ============================================
CREATE TABLE fact_macro (
    date DATE PRIMARY KEY,
    mortgage_rate_30y NUMERIC,
    case_shiller_index NUMERIC
);

COMMENT ON TABLE fact_macro IS 'National-level FRED series. Deliberately separate from metro-level tables to avoid duplicating national values across every metro row.';
COMMENT ON COLUMN fact_macro.mortgage_rate_30y IS 'Average 30-year fixed mortgage rate, percent.';

-- ============================================
-- fact_forecast: ML-predicted home value growth
-- Grain: one row = one metro + one forecast date + one model version
-- Source: internal Python forecasting pipeline, updated monthly
-- ============================================
CREATE TABLE fact_forecast (
    metro_id INT REFERENCES dim_metro(metro_id),
    forecast_date DATE NOT NULL,
    predicted_zhvi NUMERIC,
    lower_bound NUMERIC,
    upper_bound NUMERIC,
    model_version TEXT,
    created_at TIMESTAMP DEFAULT now(),
    PRIMARY KEY (metro_id, forecast_date, model_version)
);

COMMENT ON TABLE fact_forecast IS 'Model output, kept separate from fact_home_values so actuals and predictions are never mixed in the same rows.';
COMMENT ON COLUMN fact_forecast.model_version IS 'Identifier for the model run/version that produced this prediction, for reproducibility.';