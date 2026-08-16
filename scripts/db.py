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