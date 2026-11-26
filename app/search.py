"""Hybrid job search: vector + full-text, fused with RRF, optionally reranked.

Modes (the same code path is reused by the evals in Phase 8):
  vector          pgvector cosine search only
  fts             Postgres full-text search only
  hybrid          vector + fts fused with reciprocal rank fusion
  hybrid_rerank   hybrid, then a cross-encoder rescoring the top candidates
"""
import re
from functools import lru_cache

from fastembed.rerank.cross_encoder import TextCrossEncoder

from app.db import get_conn
from app.embeddings import embed_texts, to_pgvector

MODES = ("vector", "fts", "hybrid", "hybrid_rerank")
RERANK_MODEL = "Xenova/ms-marco-MiniLM-L-6-v2"
# bge models work best when a short search query gets this prefix (documents get none).
QUERY_PREFIX = "Represent this sentence for searching relevant passages: "
RRF_K = 60        # standard constant from the RRF paper
CANDIDATES = 50   # how many results each retriever contributes
RERANK_TOP = 30   # how many fused results the cross-encoder rescoring sees

STOPWORDS = {
    "a", "an", "and", "the", "of", "in", "on", "at", "to", "for", "with", "or", "is",
    "are", "i", "my", "me", "who", "that", "this", "as", "be", "by", "we", "you", "your",
}


def build_tsquery(text):
    """'Python backend engineer' -> 'python | backend | engineer' (OR semantics)."""
    seen, out = set(), []
    for w in re.findall(r"[a-z0-9]+", text.lower()):
        if len(w) < 2 or w in STOPWORDS or w in seen:
            continue
        seen.add(w)
        out.append(w)
    return " | ".join(out[:40])


SENIOR_TITLE_RE = (
    r"\m(staff|principal|senior|sr|lead|director|head|vp|manager|architect|distinguished|"
    r"fellow|research scientist|researcher|member of technical staff|phd)\M"
)


def _filters(remote_only, location, exclude_senior=False, locations=None):
    where = "expired_at IS NULL AND embedding IS NOT NULL"
    params = []
    if remote_only:
        where += " AND remote"
    if location:
        where += " AND location ILIKE %s"
        params.append(f"%{location}%")
    if locations:  # match ANY of these location terms
        where += " AND (" + " OR ".join(["location ILIKE %s"] * len(locations)) + ")"
        params.extend(f"%{l}%" for l in locations)
    if exclude_senior:
        where += " AND title !~* %s"
        params.append(SENIOR_TITLE_RE)
    return where, params

def vector_search(conn, query, where, params, limit=CANDIDATES):
    qvec = to_pgvector(embed_texts([QUERY_PREFIX + query])[0])
    rows = conn.execute(
        f"SELECT id FROM jobs WHERE {where} ORDER BY embedding <=> %s::vector LIMIT %s",
        (*params, qvec, limit),
    ).fetchall()
    return [r[0] for r in rows]


def fts_search(conn, query, where, params, limit=CANDIDATES):
    tsq = build_tsquery(query)
    if not tsq:
        return []
    rows = conn.execute(
        f"SELECT id FROM jobs, to_tsquery('english', %s) q "
        f"WHERE {where} AND fts @@ q ORDER BY ts_rank_cd(fts, q, 1) DESC LIMIT %s",
        (tsq, *params, limit),
    ).fetchall()
    return [r[0] for r in rows]


def rrf(rankings, k=RRF_K):
    """Reciprocal Rank Fusion. rankings = [[id, id, ...], [id, ...]] best first.
    Returns [(id, score)] best first. Uses rank positions only, never raw scores."""
    scores = {}
    for ranking in rankings:
        for rank, job_id in enumerate(ranking, start=1):
            scores[job_id] = scores.get(job_id, 0.0) + 1.0 / (k + rank)
    return sorted(scores.items(), key=lambda kv: kv[1], reverse=True)


def fetch_jobs(conn, ids):
    """Load job rows and return them in the same order as ids."""
    if not ids:
        return []
    rows = conn.execute(
        "SELECT id, title, company_name, location, remote, url, description, posted_at "
        "FROM jobs WHERE id = ANY(%s)",
        (list(ids),),
    ).fetchall()
    by_id = {
        r[0]: {
            "id": r[0], "title": r[1], "company_name": r[2], "location": r[3],
            "remote": r[4], "url": r[5], "description": r[6] or "", "posted_at": r[7],
        }
        for r in rows
    }
    return [by_id[i] for i in ids if i in by_id]


@lru_cache(maxsize=1)
def get_reranker():
    return TextCrossEncoder(model_name=RERANK_MODEL, cache_dir="/models")


def rerank_scores(query, jobs):
    texts = [
        f"{j['title']} at {j['company_name']}. {j['location']}. {j['description'][:1000]}"
        for j in jobs
    ]
    return [float(s) for s in get_reranker().rerank(query, texts)]


def search(query, mode="hybrid_rerank", k=10, remote_only=False, location=None,
           exclude_senior=False, locations=None):
    if mode not in MODES:
        raise ValueError(f"mode must be one of {MODES}")
    where, params = _filters(remote_only, location, exclude_senior, locations)

    with get_conn() as conn:
        vec_ids = vector_search(conn, query, where, params) if mode != "fts" else []
        fts_ids = fts_search(conn, query, where, params) if mode != "vector" else []

        scores = {}
        if mode == "vector":
            ids = vec_ids
        elif mode == "fts":
            ids = fts_ids
        else:
            fused = rrf([vec_ids, fts_ids])
            ids = [i for i, _ in fused]
            scores = dict(fused)

        pool = ids[:RERANK_TOP] if mode == "hybrid_rerank" else ids[:k]
        jobs = fetch_jobs(conn, pool)

    if mode == "hybrid_rerank" and jobs:
        for j, s in zip(jobs, rerank_scores(query, jobs)):
            j["score"] = s
        jobs.sort(key=lambda j: j["score"], reverse=True)
        jobs = jobs[:k]
    else:
        for j in jobs:
            j["score"] = scores.get(j["id"])
    return jobs