import pandas as pd
from dotenv import load_dotenv
from db import get_engine
import requests
import os

load_dotenv()
api_key = os.getenv("FRED_API_KEY")

def fetch_fred_series(series_id, column_name):
    url = "https://api.stlouisfed.org/fred/series/observations?series_id=" + series_id + "&api_key=" + api_key + "&observation_start=2000-01-01&file_type=json"

    data = requests.get(url).json()
    df = pd.DataFrame(data["observations"])

    df["date"] = pd.to_datetime(df["date"])
    df["value"] = pd.to_numeric(df["value"], errors="coerce")

    df_series = df[["date", "value"]]
    df_series = df_series.rename(columns={"value":column_name})
    
    return df_series

def fetch_and_clean_macro():
    mortgage_series = fetch_fred_series("MORTGAGE30US", "mortgage_rate_30y")
    shiller_series = fetch_fred_series("CSUSHPISA", "case_shiller_index")

    mortgage_series = mortgage_series.set_index("date").resample("ME").mean().reset_index()
    shiller_series["date"] = shiller_series["date"] + pd.offsets.MonthEnd(0)
    macro_final = mortgage_series.merge(shiller_series, on="date")
    
    return macro_final

def load_fact_macro(macro_final, engine):
    existing = pd.read_sql("SELECT COUNT(*) FROM fact_macro", engine).iloc[0, 0]
    if existing == 0:
        macro_final.to_sql("fact_macro", engine, if_exists="append", index=False)
    else:
        print(f"fact_macro already has {existing} rows")
    
if __name__ == "__main__":
    engine = get_engine()
    macro_final = fetch_and_clean_macro()
    load_fact_macro(macro_final, engine)