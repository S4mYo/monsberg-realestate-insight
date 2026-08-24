import os
import pandas as pd
import requests
from dotenv import load_dotenv
from db import get_engine

load_dotenv()
FRED_API_KEY = os.getenv("FRED_API_KEY")

FRED_BASE_URL = "https://api.stlouisfed.org/fred/series/observations"
OBSERVATION_START = "2000-01-01"


def fetch_fred_series(series_id, column_name):
    """Download one FRED series and return it as a (date, column_name) DataFrame.

    FRED marks missing observations with the string "." rather than an
    empty value, hence pd.to_numeric(errors="coerce") instead of astype.
    """
    url = (
        f"{FRED_BASE_URL}?series_id={series_id}&api_key={FRED_API_KEY}"
        f"&observation_start={OBSERVATION_START}&file_type=json"
    )

    data = requests.get(url).json()
    df = pd.DataFrame(data["observations"])

    df["date"] = pd.to_datetime(df["date"])
    df["value"] = pd.to_numeric(df["value"], errors="coerce")

    series = df[["date", "value"]].rename(columns={"value": column_name})
    return series


def fetch_and_clean_macro():
    """Fetch mortgage rate (weekly) and Case-Shiller index (monthly),
    align them to a common monthly grain, and merge them.

    Mortgage rate is resampled to month-end averages. Case-Shiller dates
    (which FRED reports as the first of the month) are shifted to
    month-end to match fact_home_values' date convention. The inner
    merge intentionally drops recent months where Case-Shiller (released
    with a ~2-3 month lag) isn't available yet.
    """
    mortgage_rate = fetch_fred_series("MORTGAGE30US", "mortgage_rate_30y")
    case_shiller = fetch_fred_series("CSUSHPISA", "case_shiller_index")

    mortgage_rate = mortgage_rate.set_index("date").resample("ME").mean().reset_index()
    case_shiller["date"] = case_shiller["date"] + pd.offsets.MonthEnd(0)

    macro_monthly = mortgage_rate.merge(case_shiller, on="date")
    return macro_monthly


def load_fact_macro(macro_monthly, engine):
    """Write new rows to fact_macro.

    Only inserts rows for dates not already present — safe to re-run
    monthly without duplicating history.
    """
    existing = pd.read_sql(
        "SELECT date FROM fact_macro", engine
        )
    existing["date"] = pd.to_datetime(existing["date"])
    
    merged = macro_monthly.merge(
        existing, on="date", how="left", indicator=True
    )
    new_rows = merged[merged["_merge"] == "left_only"].drop(columns=["_merge"])
    
    if len(new_rows) > 0:
        new_rows.to_sql("fact_macro", engine, if_exists="append", index=False)
        print(f"Inserted {len(new_rows)} new rows into fact_macro")
    else:
        print(f"No new rows to insert into fact_macro")


if __name__ == "__main__":
    engine = get_engine()
    macro_monthly = fetch_and_clean_macro()
    load_fact_macro(macro_monthly, engine)