import pandas as pd
from sqlalchemy import text
from db import get_engine


def fetch_and_clean_census(engine):
    df = pd.read_csv("https://www2.census.gov/programs-surveys/popest/datasets/2020-2025/metro/totals/cbsa-est2025-alldata.csv",encoding="latin-1")
    metro_only = df[df['LSAD'] == 'Metropolitan Statistical Area']

    metro_only["NAME_clean"] = metro_only["NAME"].str.replace("/", "-")
    city = metro_only["NAME_clean"].str.split(", ").str[0].str.split("-").str[0]
    state = metro_only["NAME_clean"].str.split(", ").str[1].str.split("-").str[0]
    metro_only["derived_name"] = city + ", " + state

    dim_metro_db = pd.read_sql("SELECT metro_id, zillow_region_name FROM dim_metro", engine)
    matched = metro_only.merge(dim_metro_db, left_on="derived_name", right_on="zillow_region_name")
    
    return matched

def dim_metro_cbsa_update(matched, engine):
    with engine.connect() as conn:
        for _, row in matched.iterrows():
            conn.execute(
                text("UPDATE dim_metro SET census_cbsa_code = :cbsa WHERE metro_id = :mid"),
                {"cbsa":row["CBSA"], "mid":row["metro_id"]}
            )
        conn.commit()

def load_fact_population(matched, engine):
    cols = [c for c in matched.columns if c.startswith("POPESTIMATE") 
            or c.startswith("NETMIG") 
            or c == "metro_id"]
    subset = matched[cols]

    long_df = pd.wide_to_long(
        subset,
        stubnames=["POPESTIMATE", "NETMIG"],
        i="metro_id",
        j="year",
        suffix=r"\d+"
    )
    long_df = long_df.reset_index().rename(columns={"POPESTIMATE":"population", "NETMIG":"net_migration"})
    
    existing = pd.read_sql("SELECT COUNT(*) FROM fact_population", engine).iloc[0,0]
    if existing == 0:
        long_df.to_sql("fact_population", engine, if_exists="append", index=False)
    else:
        print(f"fact_population already has {existing} rows")

if __name__ == "__main__":
    engine = get_engine()
    matched = fetch_and_clean_census(engine)
    dim_metro_cbsa_update(matched, engine)
    load_fact_population(matched, engine)
