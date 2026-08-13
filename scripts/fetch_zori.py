import pandas as pd
from db import get_engine

url = "https://files.zillowstatic.com/research/public_csvs/zori/Metro_zori_uc_sfrcondomfr_sm_month.csv?t=1786371714"

def get_existing_metros(engine):
    existing_metros = pd.read_sql("SELECT zillow_region_name FROM dim_metro", engine)["zillow_region_name"]
    return existing_metros

def fetch_and_clean_zori(existing_metros):
    df = pd.read_csv(url)
    df = df[df["RegionName"].isin(existing_metros)]

    id_vars = df.columns[:5].to_list()
    df_melt = df.melt(id_vars=id_vars, var_name="date", value_name="zori_value")
    df_melt["date"] = pd.to_datetime(df_melt["date"])

    return df_melt

def load_fact_rent(df_melt, engine):
    dim_metro_db = pd.read_sql("SELECT metro_id, zillow_region_name FROM dim_metro", engine)
    df_final = df_melt.merge(dim_metro_db, left_on="RegionName", right_on="zillow_region_name")
    
    to_upload = df_final[["metro_id", "date", "zori_value"]]
    
    existing_facts = pd.read_sql("SELECT COUNT(*) FROM fact_rent", engine).iloc[0, 0]
    if existing_facts == 0:
        to_upload.to_sql("fact_rent", engine, if_exists="append", index=False)
    else:
        print(f"fact_rent already has {existing_facts} rows")
        
if __name__ == "__main__":
      engine = get_engine()
      existing_metros = get_existing_metros(engine)
      df_melt = fetch_and_clean_zori(existing_metros)
      load_fact_rent(df_melt, engine)