from dotenv import load_dotenv
from sqlalchemy import create_engine
import os


def get_engine():
    """Create a SQLAlchemy engine connected to the Neon Postgres database.

    Reads DATABASE_URL from the .env file. Safe to call multiple times;
    load_dotenv() re-reading the file each time has no side effects.
    """
    load_dotenv()
    db_url = os.getenv("DATABASE_URL")
    engine = create_engine(db_url)
    return engine

def get_new_rows(incoming_df, existing_df, key_columns):
    """Return only the rows from incoming_df not already present in
    existing_df, matched on key_columns.

    Used across all fetch scripts to make loads safe to re-run: a
    re-run with no new data correctly returns an empty DataFrame.
    """
    merged = incoming_df.merge(
        existing_df, on=key_columns, how="left", indicator=True
    )
    return merged[merged["_merge"] == "left_only"].drop(columns=["_merge"])

def derive_zillow_style_name(name_series):
    """Convert a hyphenated Census/Zillow metro name to the short format
    used in dim_metro (e.g. "Chicago-Naperville-Elgin, IL-IN-WI" ->
    "Chicago, IL"). Shared by fetch_census.py and any script matching
    against Zillow's own long-form Metro names.
    """
    name_clean = name_series.str.replace("/", "-")
    city = name_clean.str.split(", ").str[0].str.split("-").str[0]
    state = name_clean.str.split(", ").str[1].str.split("-").str[0]
    return city + ", " + state