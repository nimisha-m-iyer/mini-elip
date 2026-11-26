import psycopg
from app.config import settings


def get_conn():
    # Neon's free database sleeps when idle. The wait lets it wake up.
    return psycopg.connect(settings.database_url, connect_timeout=20)