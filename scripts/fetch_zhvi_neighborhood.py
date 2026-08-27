import pandas as pd
from scripts.db import get_engine, get_new_rows, derive_zillow_style_name

NEIGHBORHOOD_ZHVI_URL = "https://files.zillowstatic.com/research/public_csvs/zhvi/Neighborhood_zhvi_uc_sfrcondo_tier_0.33_0.67_sm_sa_month.csv?t=1787729777"


def keep_primary_region_per_name(df):
    """Keep only the lowest-SizeRank row per (RegionName, City, State).

    Zillow occasionally publishes two RegionIDs for what appears to be
    the same neighborhood name (e.g. after redefining boundaries), each
    carrying its own separate price history. Keeping only the lowest
    SizeRank (Zillow's own notion of "primary") avoids inserting two
    conflicting histories under the same neighborhood_id.
    """
    return df.sort_values("SizeRank").drop_duplicates(
        subset=["RegionName", "City", "State"], keep="first"
    )

def add_size_rank_within_metro(df):
    """Add a per-metro size rank, since Zillow's own SizeRank is global
    across all US regions and isn't comparable between a large metro
    (where even a modest neighborhood ranks in the thousands) and a
    small one (where the top neighborhood might already be near 3000).

    Rank 1 = the most prominent neighborhood within that specific metro.
    """
    df["size_rank_within_metro"] = df.groupby("metro_id")["SizeRank"].rank(method="first").astype(int)
    return df

def fetch_and_clean_neighborhood_zhvi(engine):
    """Download Zillow's neighborhood-level ZHVI and match each row to
    its metro in the existing 50-metro roster.

    Zillow's neighborhood file uses the same long-form Metro naming as
    the metro-level file did before its own crosswalk fix (e.g.
    "Houston-The Woodlands-Sugar Land, TX" instead of "Houston, TX"),
    so the same derive_zillow_style_name logic applies here.
    """
    df = pd.read_csv(
        NEIGHBORHOOD_ZHVI_URL,
        storage_options={"User-Agent": "Mozilla/5.0"},
    )
    
    df = keep_primary_region_per_name(df)
    df["derived_metro_name"] = derive_zillow_style_name(df["Metro"])
    
    dim_metro_db = pd.read_sql("SELECT metro_id, zillow_region_name FROM dim_metro", engine)
    df = df.merge(dim_metro_db, left_on="derived_metro_name", right_on="zillow_region_name")
    df = add_size_rank_within_metro(df)
    
    id_vars = ["RegionName", "City", "State", "SizeRank", "size_rank_within_metro", "metro_id"]
    date_cols = [c for c in df.columns if c[:4].isdigit()]
    
    neighborhood_long = df.melt(
        id_vars=id_vars, value_vars=date_cols, var_name="date", value_name="zhvi_value"
    )
    
    neighborhood_long["date"] = pd.to_datetime(neighborhood_long["date"])
    neighborhood_long = neighborhood_long.dropna(subset=["zhvi_value"])
    
    return neighborhood_long

def load_dim_neighborhood(neighborhood_long, engine):
    """Populate dim_neighborhood with the neighborhood roster, once per
    metro's first appearance.

    Uses get_new_rows on (zillow_region_name, metro_id) so re-running
    this after Zillow adds new neighborhoods to their coverage would
    correctly pick up only the new ones, not just skip everything
    because dim_neighborhood already has some rows.
    """
    neighborhoods = neighborhood_long[["RegionName", "City", "State", "SizeRank", "size_rank_within_metro", "metro_id"]].drop_duplicates()
    neighborhoods = neighborhoods.rename(columns={
        "RegionName": "zillow_region_name",
        "City": "city",
        "State": "state",
        "SizeRank": "size_rank"
    })
    
    existing = pd.read_sql("SELECT zillow_region_name, city, metro_id FROM dim_neighborhood", engine)
    
    new_rows = get_new_rows(neighborhoods, existing, key_columns=["zillow_region_name", "city", "metro_id"])
    
    if len(new_rows) > 0:
        new_rows.to_sql("dim_neighborhood", engine, if_exists="append", index=False)
        print(f"Inserted {len(new_rows)} new rows into dim_neighborhood")
    else:
        print("No new rows to insert into dim_neighborhood")
        
def load_fact_neighborhood_home_values(neighborhood_long, engine):
    """Join neighborhood ZHVI rows to their neighborhood_id and write
    new rows to fact_neighborhood_home_values.

    Only inserts (neighborhood_id, date) combinations not already
    present — same safe-to-re-run pattern as the metro-level fact
    tables.
    """
    dim_neighborhood_db = pd.read_sql(
        "SELECT neighborhood_id, zillow_region_name, city, metro_id FROM dim_neighborhood",
        engine
    )
    
    neighborhood_with_id = neighborhood_long.merge(
        dim_neighborhood_db,
        left_on=["RegionName", "City", "metro_id"],
        right_on=["zillow_region_name", "city", "metro_id"]
    )
    
    to_upload = neighborhood_with_id[["neighborhood_id", "date", "zhvi_value"]]
    
    existing = pd.read_sql("SELECT neighborhood_id, date FROM fact_neighborhood_home_values", engine)
    existing["date"] = pd.to_datetime(existing["date"])
    
    new_rows = get_new_rows(to_upload, existing, key_columns=["neighborhood_id", "date"])
    
    
    if len(new_rows) > 0:
        new_rows.to_sql(
            "fact_neighborhood_home_values",
            engine,
            if_exists="append",
            index=False,
            chunksize=10000,
            method="multi"
            )
        print(f"Inserted {len(new_rows)} new rows into fact_neighborhood_home_values")
    else:
        print("No new rows to insert into fact_neighborhood_home_values")
            
if __name__ == "__main__":
    engine = get_engine()
    result = fetch_and_clean_neighborhood_zhvi(engine)
    load_dim_neighborhood(result, engine)
    load_fact_neighborhood_home_values(result, engine)