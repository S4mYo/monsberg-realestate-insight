import pandas as pd
from db import get_engine

url = "https://files.zillowstatic.com/research/public_csvs/zhvi/Metro_zhvi_uc_sfrcondo_tier_0.33_0.67_sm_sa_month.csv?t=1786371714"

def fetch_and_clean_zhvi():
    df = pd.read_csv(url)
    df = df[(df["SizeRank"] > 0)].nsmallest(50, "SizeRank")
    
    id_vars = df.columns[:5].tolist()

    df_melt = df.melt(id_vars=id_vars, var_name="date", value_name="zhvi_value")
    df_melt["home_type"] = "all_homes"
    df_melt["date"] = pd.to_datetime(df_melt["date"])
    
    return df_melt

def load_dim_metro(df_melt, engine):
    metros = df_melt[["RegionName", "StateName"]].drop_duplicates()
    metros = metros.rename(columns={"RegionName":"zillow_region_name", "StateName":"state"})

    existing_count = pd.read_sql("SELECT COUNT(*) FROM dim_metro", engine).iloc[0, 0]
    if existing_count == 0:
        metros.to_sql("dim_metro", engine, if_exists="append", index=False)
    else:
        print(f"dim_metro už obsahuje {existing_count} riadkov, preskakujem zápis")

def load_fact_home_values(df_melt, engine):
    dim_metro_db = pd.read_sql("SELECT metro_id, zillow_region_name FROM dim_metro", engine)
    df_final = df_melt.merge(dim_metro_db, left_on="RegionName", right_on="zillow_region_name")
    to_upload = df_final[["metro_id", "date", "home_type", "zhvi_value"]]

    existing_facts = pd.read_sql("SELECT COUNT(*) FROM fact_home_values", engine).iloc[0, 0]
    if existing_facts == 0:
        to_upload.to_sql("fact_home_values", engine, if_exists="append", index=False)
    else:
        print(f"fact_home_values už obsahuje {existing_facts} riadkov, preskakujem zápis")

if __name__ == "__main__":
      engine = get_engine()
      df_melt = fetch_and_clean_zhvi()
      load_dim_metro(df_melt, engine)
      load_fact_home_values(df_melt, engine)