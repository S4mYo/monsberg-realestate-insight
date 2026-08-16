import pandas as pd
from sqlalchemy import text
from db import get_engine

CENSUS_URL = "https://www2.census.gov/programs-surveys/popest/datasets/2020-2025/metro/totals/cbsa-est2025-alldata.csv"
METRO_LSAD = "Metropolitan Statistical Area"


def fetch_and_clean_census(engine):
    """Download Census population estimates and match them to dim_metro.

    The file mixes metro-level summary rows with county-level breakdown
    rows sharing the same CBSA code, so it's filtered to METRO_LSAD only
    (see LSAD value_counts from earlier exploration).

    Census names metros with all constituent cities, e.g.
    "Albany-Schenectady-Troy, NY", while Zillow uses just the principal
    city, e.g. "Albany, NY". derived_name approximates the Zillow format
    by taking the text before the first hyphen on each side of the comma.
    Louisville uses a slash ("Louisville/Jefferson County, KY-IN") instead
    of a hyphen, so slashes are normalized to hyphens first. This matches
    all 50 roster metros as of the 2025 vintage; a future Census release
    could introduce a new naming pattern that needs its own fix.

    encoding="latin-1" is required: the file isn't valid UTF-8.
    storage_options sets a browser-like User-Agent because Cloudflare
    blocks pandas' default "Python-urllib" user agent with a 403.
    """
    df = pd.read_csv(
        CENSUS_URL,
        encoding="latin-1",
        storage_options={"User-Agent": "Mozilla/5.0"},
    )
    metro_only = df[df["LSAD"] == METRO_LSAD]

    name_clean = metro_only["NAME"].str.replace("/", "-")
    city = name_clean.str.split(", ").str[0].str.split("-").str[0]
    state = name_clean.str.split(", ").str[1].str.split("-").str[0]
    metro_only["derived_name"] = city + ", " + state

    dim_metro_db = pd.read_sql("SELECT metro_id, zillow_region_name FROM dim_metro", engine)
    census_with_metro_id = metro_only.merge(
        dim_metro_db, left_on="derived_name", right_on="zillow_region_name"
    )

    return census_with_metro_id


def update_dim_metro_cbsa(census_with_metro_id, engine):
    """Backfill dim_metro.census_cbsa_code for each matched metro.

    An UPDATE, not an INSERT, so it's safe to re-run: repeating it just
    overwrites each row with the same value.
    """
    with engine.connect() as conn:
        for _, row in census_with_metro_id.iterrows():
            conn.execute(
                text("UPDATE dim_metro SET census_cbsa_code = :cbsa WHERE metro_id = :mid"),
                {"cbsa": row["CBSA"], "mid": row["metro_id"]},
            )
        conn.commit()


def load_fact_population(census_with_metro_id, engine):
    """Reshape wide POPESTIMATE{year}/NETMIG{year} columns into one row
    per (metro, year), and write the result to fact_population."""
    year_cols = [
        c for c in census_with_metro_id.columns
        if c.startswith("POPESTIMATE") or c.startswith("NETMIG") or c == "metro_id"
    ]
    subset = census_with_metro_id[year_cols]

    population_long = pd.wide_to_long(
        subset,
        stubnames=["POPESTIMATE", "NETMIG"],
        i="metro_id",
        j="year",
        suffix=r"\d+",
    )
    population_long = population_long.reset_index().rename(
        columns={"POPESTIMATE": "population", "NETMIG": "net_migration"}
    )

    existing = pd.read_sql("SELECT COUNT(*) FROM fact_population", engine).iloc[0, 0]
    if existing == 0:
        population_long.to_sql("fact_population", engine, if_exists="append", index=False)
    else:
        print(f"fact_population already has {existing} rows")


if __name__ == "__main__":
    engine = get_engine()
    census_with_metro_id = fetch_and_clean_census(engine)
    update_dim_metro_cbsa(census_with_metro_id, engine)
    load_fact_population(census_with_metro_id, engine)