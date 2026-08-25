import pandas as pd
import numpy as np
from sqlalchemy import text
from scripts.db import get_engine
from xgboost import XGBRegressor
from sklearn.metrics import mean_absolute_percentage_error, mean_absolute_error

LAG_WINDOWS = [1, 3, 6, 12]
FEATURES = ["metro_id"] + [f"lag_{w}" for w in LAG_WINDOWS] + ["month"]
FORECAST_HORIZON_MONTHS = 12
TEST_WINDOW_MONTHS = 12
MODEL_VERSION = "xgb_v1"


def add_lag_features(df, lag_windows):
    """Add lagged pct_change columns, grouped by metro so lags never
    cross metro boundaries."""
    for lag in lag_windows:
        df[f"lag_{lag}"] = df.groupby("metro_id")["pct_change"].shift(lag)
    return df

def prepare_data(engine):
    """Load ZHVI price history and engineer features for the forecast model.

    The model predicts month-over-month percent change (pct_change), not
    the raw price. Tree models like XGBoost can't extrapolate beyond the
    value range seen in training, and ZHVI only ever grows, so a price
    target would eventually fall outside that range. pct_change and the
    lag features built from it stay in a stable, recurring range instead.

    Inputs are limited to the metro's own price history (lag features)
    and calendar month. Anything that itself requires a future forecast
    (mortgage rate, Case-Shiller) is excluded to avoid feature leakage:
    at prediction time, next month's macro values don't exist yet.

    Returns:
        price_history: full history with lag features, used for training.
        recent_history: each metro's most recent FORECAST_HORIZON_MONTHS
            rows, used as the starting point for recursive_forecast.
    """
    price_history = pd.read_sql(
        "SELECT metro_id, date, zhvi_value FROM fact_home_values "
        "WHERE home_type = 'all_homes' ORDER BY metro_id, date",
        engine,
    )

    # groupby prevents pct_change/shift from crossing metro boundaries -
    # without it, the first row of metro B would compute its change
    # against the last row of metro A.
    price_history["pct_change"] = price_history.groupby("metro_id")["zhvi_value"].pct_change()
    price_history["date"] = pd.to_datetime(price_history["date"])
    price_history = price_history.dropna(subset=["pct_change"])

    recent_history = price_history.groupby("metro_id").tail(FORECAST_HORIZON_MONTHS)

    price_history = add_lag_features(price_history, LAG_WINDOWS)
    price_history["month"] = price_history["date"].dt.month
    price_history = price_history.dropna(subset=[f"lag_{w}" for w in LAG_WINDOWS])

    return price_history, recent_history


def train_and_evaluate(price_history):
    """Train on all but the last TEST_WINDOW_MONTHS, then report MAE/MAPE
    against two baselines to check the model adds real value.

    Split is chronological, not random: a random split would let the
    model train on rows chronologically after ones it's tested on -
    the same future-leakage problem the feature choice avoids.

    MAPE is reported for reference but is unreliable here since
    pct_change often sits near zero, making its percentage blow up;
    MAE is the metric that actually matters.
    """
    cutoff_date = price_history["date"].max() - pd.DateOffset(months=TEST_WINDOW_MONTHS)
    train = price_history[price_history["date"] <= cutoff_date]
    test = price_history[price_history["date"] > cutoff_date]

    X_train, y_train = train[FEATURES], train["pct_change"]
    X_test, y_test = test[FEATURES], test["pct_change"]

    model = XGBRegressor(n_estimators=100, max_depth=4, learning_rate=0.1, random_state=42)
    model.fit(X_train, y_train)

    predictions = model.predict(X_test)
    print(f"MAPE: {mean_absolute_percentage_error(y_test, predictions):.4f}")
    print(f"MAE: {mean_absolute_error(y_test, predictions):.5f}")

    baseline_zero = mean_absolute_error(y_test, np.zeros(len(y_test)))
    print(f"Baseline (always 0): {baseline_zero:.5f}")

    # Naive baseline: predict last month's change repeats. Prices have
    # strong momentum, so this is a genuinely hard baseline to beat -
    # a small improvement over it is a real, honest result.
    baseline_naive = mean_absolute_error(y_test, X_test["lag_1"])
    print(f"Baseline (same as month before): {baseline_naive:.5f}")


def train_final_model(price_history):
    """Retrain on the full history (train+test) for the production model
    used in recursive_forecast, now that train_and_evaluate has already
    given an honest read on out-of-sample performance."""
    X_full, y_full = price_history[FEATURES], price_history["pct_change"]

    final_model = XGBRegressor(n_estimators=100, max_depth=4, learning_rate=0.1, random_state=42)
    final_model.fit(X_full, y_full)

    return final_model


def recursive_forecast(model, recent_history):
    """Predict ZHVI FORECAST_HORIZON_MONTHS ahead for every metro.

    The model predicts one month at a time. Each month's predicted
    pct_change is appended to that metro's history and becomes the lag
    input for the next month - the model's own prior prediction feeds
    the next step, hence "recursive". Predicted prices are built up from
    the last known real price by compounding each step's predicted change.
    """
    forecast_rows = []
    for metro_id in recent_history["metro_id"].unique():
        metro_history = recent_history[recent_history["metro_id"] == metro_id].sort_values("date")

        change_history = metro_history["pct_change"].tolist()
        last_price = metro_history["zhvi_value"].iloc[-1]
        last_date = metro_history["date"].iloc[-1]

        for _ in range(FORECAST_HORIZON_MONTHS):
            target_date = last_date + pd.offsets.MonthEnd(1)

            lag_values = [change_history[-lag] for lag in LAG_WINDOWS]
            feature_values = [metro_id] + lag_values + [target_date.month]
            
            feature_row = pd.DataFrame([feature_values], columns=FEATURES)
            predicted_change = model.predict(feature_row)[0]

            predicted_price = last_price * (1 + predicted_change)

            change_history.append(predicted_change)
            last_price = predicted_price
            last_date = target_date

            forecast_rows.append((metro_id, target_date, predicted_price))

    forecast_df = pd.DataFrame(
        forecast_rows, columns=["metro_id", "forecast_date", "predicted_zhvi"]
    )
    forecast_df["model_version"] = MODEL_VERSION

    return forecast_df


def load_fact_forecast(forecast_df, engine):
    """Replace fact_forecast with the latest forecast.

    Deletes all existing rows and inserts the new forecast — safe to
    re-run monthly. Historical forecast snapshots aren't preserved;
    the dashboard only needs the current forecast, not a version history.
    """
    with engine.connect() as conn:
        conn.execute(text("DELETE FROM fact_forecast"))
        conn.commit()

    forecast_df.to_sql("fact_forecast", engine, if_exists="append", index=False)
    print(f"Replaced fact_forecast with {len(forecast_df)} new rows")

def is_forecast_stale(latest_data_date, forecast_created):
    """Compare the latest price data date against when the forecast was
    last generated, to decide whether a re-run is needed.

    Returns True if there's no forecast yet, or if new price data has
    arrived since the forecast was last created.
    """
    if forecast_created is None:
        return True
    
    latest_data_date = pd.to_datetime(latest_data_date)
    forecast_created = pd.to_datetime(forecast_created)
    
    return latest_data_date > forecast_created

def should_run_forecast(engine):
    """Check whether new ZHVI data has arrived since the last forecast run.

    Compares the latest fact_home_values date against the forecast's
    created_at timestamp — skips the (expensive) model retraining and
    recursive prediction if nothing has changed since the last run.
    """
    latest_data_date = pd.read_sql(
        "SELECT MAX(date) AS latest FROM fact_home_values", engine
    ).iloc[0,0]
    
    forecast_created = pd.read_sql(
        "SELECT MAX(created_at) AS latest FROM fact_forecast", engine
    ).iloc[0,0]

    return is_forecast_stale(latest_data_date, forecast_created)


if __name__ == "__main__":
    engine = get_engine()
    
    if not should_run_forecast(engine):
        print("No new ZHVI data since last forecast run - skipping")
    else:
        price_history, recent_history = prepare_data(engine)
        train_and_evaluate(price_history)
        model = train_final_model(price_history)
        forecast_df = recursive_forecast(model, recent_history)
        load_fact_forecast(forecast_df, engine)