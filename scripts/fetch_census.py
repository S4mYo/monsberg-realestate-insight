import pandas as pd
from sqlalchemy import text
from scripts.db import get_engine, get_new_rows
import requests
from datetime import date


METRO_LSAD = "Metropolitan Statistical Area"

def get_latest_census_vintage():
    """Find the latest available Census vintage by checking which
    vintage-year URL actually resolves, starting from the estimated
    latest year and falling back to earlier ones if not yet published.
    """
    current_year = date.today().year
    for vintage in [current_year - 1, current_year - 2, current_year - 3]:
        url = (
            f"https://www2.census.gov/programs-surveys/popest/datasets/"
            f"2020-{vintage}/metro/totals/cbsa-est{vintage}-alldata.csv"
        )
        response = requests.head(url, headers={"User-Agent": "Mozilla/5.0"})
        if response.status_code == 200:
            return vintage
    raise RuntimeError("Could not find a valid Census vintage URL")

def derive_zillow_style_name(name_series):
    """Convert Census metro names to Zillow's naming format.

    Census: "Albany-Schenectady-Troy, NY" (all constituent cities)
    Zillow: "Albany, NY" (principal city only)

    Takes the text before the first hyphen on each side of the comma.
    Slashes (e.g. "Louisville/Jefferson County, KY-IN") are normalized
    to hyphens first, so both separators are handled the same way.
    """
    name_clean = name_series.str.replace("/", "-")
    city = name_clean.str.split(", ").str[0].str.split("-").str[0]
    state = name_clean.str.split(", ").str[1].str.split("-").str[0]
    return city + ", " + state

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
    vintage = get_latest_census_vintage()
    census_url = (
        f"https://www2.census.gov/programs-surveys/popest/datasets/"
        f"2020-{vintage}/metro/totals/cbsa-est{vintage}-alldata.csv"
    )

    df = pd.read_csv(
        census_url,
        encoding="latin-1",
        storage_options={"User-Agent": "Mozilla/5.0"},
    )
    metro_only = df[df["LSAD"] == METRO_LSAD]

    metro_only["derived_name"] = derive_zillow_style_name(metro_only["NAME"])

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
    per (metro, year), and write new rows to fact_population.

    Only inserts (metro_id, year) combinations not already present —
    safe to re-run annually without duplicating history. Census
    typically republishes the same vintage file unchanged between runs,
    so a re-run without new data correctly inserts nothing.
    """
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

    existing = pd.read_sql(
        "SELECT metro_id, year FROM fact_population", engine
        )
    
    new_rows = get_new_rows(population_long, existing, key_columns=["metro_id", "year"])
    
    if len(new_rows) > 0:
        new_rows.to_sql("fact_population", engine, if_exists="append", index=False)
        print(f"Inserted {len(new_rows)} new rows into fact_population")
    else:
        print(f"No new rows to insert into fact_population")


if __name__ == "__main__":
    engine = get_engine()
    census_with_metro_id = fetch_and_clean_census(engine)
    update_dim_metro_cbsa(census_with_metro_id, engine)
    load_fact_population(census_with_metro_id, engine)