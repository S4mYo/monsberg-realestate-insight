from dotenv import load_dotenv
from sqlalchemy import create_engine
import os

def get_engine():
    load_dotenv()
    db_url = os.getenv("DATABASE_URL")
    engine = create_engine(db_url)
    return engine