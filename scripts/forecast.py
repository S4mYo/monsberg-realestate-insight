import pandas as pd
import numpy as np
from db import get_engine
from xgboost import XGBRegressor
from sklearn.metrics import mean_absolute_percentage_error, mean_absolute_error

LAG_WINDOWS = [1,3,6,12]
FEATURES = ["metro_id"] + [f"lag_{w}" for w in LAG_WINDOWS] + ["month"]
FORECAST_HORIZON_MONTHS = 12
TEST_WINDOWS_MONTHS = 12

def prepare_data(engine):
    price_history = pd.read_sql("SELECT metro_id, date, zhvi_value FROM fact_home_values WHERE home_type = 'all_homes' ORDER BY metro_id, date", engine)

    price_history["pct_change"] = price_history.groupby("metro_id")["zhvi_value"].pct_change()
    price_history["date"] = pd.to_datetime(price_history["date"])
    price_history = price_history.dropna(subset=["pct_change"])

    recent_history = price_history.groupby("metro_id").tail(FORECAST_HORIZON_MONTHS)

    for lag in LAG_WINDOWS:
        price_history[f"lag_{lag}"] = price_history.groupby("metro_id")["pct_change"].shift(lag)

    price_history["month"] = price_history["date"].dt.month
    price_history = price_history.dropna(subset=[f"lag_{w}" for w in LAG_WINDOWS])
    
    return price_history, recent_history

def train_and_evaluate(df):
    cutoff_date = df["date"].max() - pd.DateOffset(months=TEST_WINDOWS_MONTHS)
    train = df[df["date"] <= cutoff_date]
    test = df[df["date"] > cutoff_date]

    X_train = train[FEATURES]
    y_train = train["pct_change"]

    X_test = test[FEATURES]
    y_test = test["pct_change"]

    model = XGBRegressor(n_estimators=100, max_depth=4, learning_rate=0.1, random_state=42)
    model.fit(X_train, y_train)

    predictions = model.predict(X_test)
    mape = mean_absolute_percentage_error(y_test, predictions)
    mae = mean_absolute_error(y_test, predictions)
    print(f"MAPE: {mape:.4f}")
    print(f"MAE: {mae:.5f}")

    baseline_zero = mean_absolute_error(y_test, np.zeros(len(y_test)))
    print(f"Baseline (always 0): {baseline_zero:.5f}")

    baseline_naive = mean_absolute_error(y_test, X_test["lag_1"])
    print(f"Baseline (same as month before): {baseline_naive:.5f}")

def train_final_model(price_history):
    X_full = price_history[FEATURES]
    y_full = price_history["pct_change"]

    final_model = XGBRegressor(n_estimators=100, max_depth=4, learning_rate=0.1, random_state=42)
    final_model.fit(X_full, y_full)
    
    return final_model

def recursive_forecast(model, recent_history):
    predicted_prices = []
    for metro_id in recent_history['metro_id'].unique():
        sub = recent_history[recent_history["metro_id"] == metro_id]
        sub = sub.sort_values("date")

        history = sub["pct_change"].tolist()

        last_value = sub["zhvi_value"].iloc[-1]
        last_date = sub["date"].iloc[-1]
        
        
        for _ in range(1,FORECAST_HORIZON_MONTHS+1):
            target_date = last_date + pd.offsets.MonthEnd(1)
            month = target_date.month
            
            lag_1 = history[-1]
            lag_3 = history[-3]
            lag_6 = history[-6]
            lag_12 = history[-12]

            values = [metro_id, lag_1, lag_3, lag_6, lag_12, month]
            row = pd.DataFrame([values], columns=FEATURES)
            rate = model.predict(row)[0]
            
            predicted_value = (1 + rate) * last_value
            
            history.append(rate)
            last_value = predicted_value
            last_date = target_date
            
            predicted_prices.append((metro_id, target_date, predicted_value))
            
    results_df = pd.DataFrame(predicted_prices, columns=["metro_id", "forecast_date", "predicted_zhvi"])
    results_df["model_version"] = "xgb_v1"
    
    return results_df

def load_fact_forecast(results_df, engine):
    existing = pd.read_sql("SELECT COUNT(*) FROM fact_forecast", engine).iloc[0,0]
    if existing == 0:
        results_df.to_sql("fact_forecast", engine, if_exists="append", index=False)
    else:
        print(f"fact_forecast already has {existing} rows")
    
if __name__ == "__main__":
    engine = get_engine()
    price_history, recent_history = prepare_data(engine)
    train_and_evaluate(price_history)
    model = train_final_model(price_history)
    results_df = recursive_forecast(model, recent_history)
    load_fact_forecast(results_df, engine)