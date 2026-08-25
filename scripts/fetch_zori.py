import pandas as pd
from scripts.db import get_engine, get_new_rows

ZORI_URL = "https://files.zillowstatic.com/research/public_csvs/zori/Metro_zori_uc_sfrcondomfr_sm_month.csv?t=1786371714"


def get_existing_metros(engine):
    """Return the zillow_region_name values already in dim_metro.

    Used to filter ZORI to the fixed 50-metro roster set by fetch_zhvi.py,
    since ZORI's own SizeRank ranking may not match ZHVI's exactly.
    """
    existing_metros = pd.read_sql("SELECT zillow_region_name FROM dim_metro", engine)["zillow_region_name"]
    return existing_metros


def fetch_and_clean_zori(existing_metros):
    """Download Zillow ZORI (rent) data and reshape it into long format,
    keeping only metros already present in dim_metro."""
    df = pd.read_csv(ZORI_URL)
    df = df[df["RegionName"].isin(existing_metros)]

    # First 5 columns are metadata; the rest are one column per month.
    id_vars = df.columns[:5].tolist()
    zori_long = df.melt(id_vars=id_vars, var_name="date", value_name="zori_value")
    zori_long["date"] = pd.to_datetime(zori_long["date"])

    return zori_long


def load_fact_rent(zori_long, engine):
    """Join ZORI rows to their metro_id and write new rows to fact_rent.

    Only inserts rows for (metro_id, date) combinations not already
    present — safe to re-run monthly without duplicating history.
    """
    dim_metro_db = pd.read_sql("SELECT metro_id, zillow_region_name FROM dim_metro", engine)
    zori_with_id = zori_long.merge(dim_metro_db, left_on="RegionName", right_on="zillow_region_name")

    to_upload = zori_with_id[["metro_id", "date", "zori_value"]]

    existing = pd.read_sql(
        "SELECT metro_id, date FROM fact_rent", engine
        )
    existing["date"] = pd.to_datetime(existing["date"])
    
    new_rows = get_new_rows(to_upload, existing, ["metro_id", "date"])
    
    if len(new_rows) > 0:
        new_rows.to_sql("fact_rent", engine, if_exists="append", index=False)
        print(f"Inserted {len(new_rows)} new rows into fact_rent")
    else:
        print("No new rows to insert into fact_rent")

if __name__ == "__main__":
    engine = get_engine()
    existing_metros = get_existing_metros(engine)
    zori_long = fetch_and_clean_zori(existing_metros)
    load_fact_rent(zori_long, engine)