import pandas as pd
from scripts.forecast import add_lag_features, recursive_forecast, FEATURES, is_forecast_stale

def test_lag_1_shifts_by_one_row():
    """lag_1 for a given row equals pct_change from the row before it."""
    df = pd.DataFrame({
        "metro_id": [1, 1, 1],
        "pct_change": [0.01, 0.02, 0.03],
    })
    result = add_lag_features(df, lag_windows=[1])

    assert pd.isna(result["lag_1"].iloc[0])
    assert result["lag_1"].iloc[1] == 0.01
    assert result["lag_1"].iloc[2] == 0.02

def test_lag_windows_do_not_cross_metro_boundaries():
    """Test first rows of a new metro should have blank lags, not values
    borrowed from the previous metro's last rows."""
    df = pd.DataFrame({
        "metro_id": [1,1,2,2],
        "pct_change": [0.01, 0.02, 0.03, 0.04],
    })
    result = add_lag_features(df, lag_windows=[1])
    
    metro_2_first_lag = result[result["metro_id"] == 2]["lag_1"].iloc[0]
    assert pd.isna(metro_2_first_lag)
    
def test_multiple_lag_windows_created_independently():
    """Each requested lag windows gets its own correctly shifted column."""
    df = pd.DataFrame({
        "metro_id": [1] * 5,
        "pct_change": [0.01, 0.02, 0.03, 0.04, 0.05],
    })
    result = add_lag_features(df, lag_windows=[1, 3])

    assert pd.isna(result["lag_1"].iloc[0])
    assert result["lag_1"].iloc[1:].tolist() == [0.01, 0.02, 0.03, 0.04]

    assert result["lag_3"].iloc[:3].isna().all()
    assert result["lag_3"].iloc[3:].tolist() == [0.01, 0.02]


def test_two_metros_each_keep_their_own_lag_sequence():
    """With two interleaved metros, each metro's lag values come only
    from its own pct_change history."""
    df = pd.DataFrame({
        "metro_id": [1, 1, 1, 2, 2, 2],
        "pct_change": [0.10, 0.11, 0.12, 0.50, 0.51, 0.52],
    })
    result = add_lag_features(df, lag_windows=[1])

    metro_1_lags = result[result["metro_id"] == 1]["lag_1"]
    metro_2_lags = result[result["metro_id"] == 2]["lag_1"]

    assert pd.isna(metro_1_lags.iloc[0])
    assert metro_1_lags.iloc[1:].tolist() == [0.10, 0.11]

    assert pd.isna(metro_2_lags.iloc[0])
    assert metro_2_lags.iloc[1:].tolist() == [0.50, 0.51]

class FakeModel:
    """A stand-in for XGBRegressor that always predicts a fixed change,
    so tests can check the forecasting loop's mechanics without training
    a real model."""
    def predict(self, feature_row):
        assert list(feature_row.columns) == FEATURES
        return [0.01]
    
def test_recursive_fore_cast_produces_correct_row_count():
    """One forecast row per metro per forecast month."""
    recent_history = pd.DataFrame({
        "metro_id": [1] * 12,
        "date": pd.date_range("2025-01-31", periods=12, freq="ME"),
        "pct_change": [0.01] * 12,
        "zhvi_value": [100000] * 12,
    })
    
    result = recursive_forecast(FakeModel(), recent_history)
    
    assert len(result) == 12

def test_recursive_forecast_compounds_price_correctly():
    """With a fixed 1% predicted change each month, the first predicted
    price should equal last_price * 1.01."""
    recent_history = pd.DataFrame({
        "metro_id": [1] * 12,
        "date": pd.date_range("2025-01-31", periods=12, freq="ME"),
        "pct_change": [0.01] * 12,
        "zhvi_value": [100000] * 12,
    })

    result = recursive_forecast(FakeModel(), recent_history)

    first_month_price = result.iloc[0]["predicted_zhvi"]
    assert abs(first_month_price - 100000 * 1.01) < 0.01
    
def test_no_existing_forecast_means_stale():
    """If fact_forecast is empty (forecast_created is None), a run is needed."""
    assert is_forecast_stale(latest_data_date="2026-07-31", forecast_created=None) is True


def test_newer_data_than_forecast_means_stale():
    """New price data arrived after the last forecast was created."""
    result = is_forecast_stale(
        latest_data_date="2026-08-31",
        forecast_created="2026-08-16 16:26:45",
    )
    assert result is True


def test_forecast_already_covers_latest_data():
    """The forecast was created after the latest data point — no new data
    has arrived, so no re-run is needed."""
    result = is_forecast_stale(
        latest_data_date="2026-07-31",
        forecast_created="2026-08-16 16:26:45",
    )
    assert result is False