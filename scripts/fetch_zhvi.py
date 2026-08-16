import pandas as pd
from db import get_engine

ZHVI_URL = "https://files.zillowstatic.com/research/public_csvs/zhvi/Metro_zhvi_uc_sfrcondo_tier_0.33_0.67_sm_sa_month.csv?t=1786371714"
TOP_N_METROS = 50


def fetch_and_clean_zhvi():
    """Download Zillow ZHVI (home value) data and reshape it into long format.

    Keeps only the top TOP_N_METROS metros by size (excluding the national
    aggregate row, SizeRank 0). Uses nsmallest instead of a SizeRank <= N
    filter because SizeRank sometimes has gaps (metro area redefinitions),
    so nsmallest reliably returns exactly N rows regardless.
    """
    df = pd.read_csv(ZHVI_URL)
    df = df[df["SizeRank"] > 0].nsmallest(TOP_N_METROS, "SizeRank")

    # First 5 columns are metadata (RegionID, SizeRank, RegionName,
    # RegionType, StateName); the rest are one column per month.
    id_vars = df.columns[:5].tolist()

    zhvi_long = df.melt(id_vars=id_vars, var_name="date", value_name="zhvi_value")
    zhvi_long["home_type"] = "all_homes"
    zhvi_long["date"] = pd.to_datetime(zhvi_long["date"])

    return zhvi_long


def load_dim_metro(zhvi_long, engine):
    """Populate dim_metro with the metro roster, once.

    This is the one-time initialization step: the 50 metros written here
    become the fixed roster for all future monthly updates. Skips the
    write if dim_metro is already populated.
    """
    metros = zhvi_long[["RegionName", "StateName"]].drop_duplicates()
    metros = metros.rename(columns={"RegionName": "zillow_region_name", "StateName": "state"})

    existing_count = pd.read_sql("SELECT COUNT(*) FROM dim_metro", engine).iloc[0, 0]
    if existing_count == 0:
        metros.to_sql("dim_metro", engine, if_exists="append", index=False)
    else:
        print(f"dim_metro already has {existing_count} rows")


def load_fact_home_values(zhvi_long, engine):
    """Join ZHVI rows to their metro_id and write them to fact_home_values."""
    dim_metro_db = pd.read_sql("SELECT metro_id, zillow_region_name FROM dim_metro", engine)
    zhvi_with_id = zhvi_long.merge(dim_metro_db, left_on="RegionName", right_on="zillow_region_name")
    to_upload = zhvi_with_id[["metro_id", "date", "home_type", "zhvi_value"]]

    existing_facts = pd.read_sql("SELECT COUNT(*) FROM fact_home_values", engine).iloc[0, 0]
    if existing_facts == 0:
        to_upload.to_sql("fact_home_values", engine, if_exists="append", index=False)
    else:
        print(f"fact_home_values already has {existing_facts} rows")


if __name__ == "__main__":
    engine = get_engine()
    zhvi_long = fetch_and_clean_zhvi()
    load_dim_metro(zhvi_long, engine)
    load_fact_home_values(zhvi_long, engine)