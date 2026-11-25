from fastapi import FastAPI, HTTPException, Query

from app.db import get_conn
from app.search import MODES, search

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


@app.get("/search")
def search_endpoint(
    q: str = Query(..., min_length=2, max_length=500),
    mode: str = "hybrid_rerank",
    k: int = Query(10, ge=1, le=50),
    remote_only: bool = False,
    location: str | None = None,
):
    if mode not in MODES:
        raise HTTPException(400, f"mode must be one of {MODES}")
    jobs = search(q, mode=mode, k=k, remote_only=remote_only, location=location)
    for j in jobs:
        j["description"] = j["description"][:300]
    return {"query": q, "mode": mode, "count": len(jobs), "results": jobs}