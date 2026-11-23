from fastapi import FastAPI
from app.db import get_conn

app = FastAPI(title="mini-elip")


@app.get("/health")
def health():
    status = {"status": "ok", "db": False, "pgvector": False}
    try:
        with get_conn() as conn:
            conn.execute("SELECT 1")
            status["db"] = True
            row = conn.execute(
                "SELECT 1 FROM pg_extension WHERE extname = 'vector'"
            ).fetchone()
            status["pgvector"] = row is not None
    except Exception as e:
        status["status"] = "error"
        status["error"] = str(e)
    return status