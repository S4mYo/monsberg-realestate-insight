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