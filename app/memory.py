"""Per-user memory in Postgres: preferences, jobs shown, feedback."""
import json

import numpy as np
from pydantic import BaseModel, Field, field_validator

from app.db import get_conn


class Preferences(BaseModel):
    remote_only: bool = False
    locations: list[str] = Field(default_factory=list)
    avoid_companies: list[str] = Field(default_factory=list)
    focus: str = ""

    @field_validator("locations", "avoid_companies", mode="before")
    @classmethod
    def clean_list(cls, v):
        if v is None:
            return []
        if isinstance(v, str):
            v = [v]
        out = []
        for x in v:
            s = str(x).strip()
            if s and s.lower() not in [o.lower() for o in out]:
                out.append(s)
        return out[:10]

    @field_validator("focus", mode="before")
    @classmethod
    def clean_focus(cls, v):
        return str(v or "").strip()[:200]


def get_preferences(uid) -> Preferences:
    with get_conn() as conn:
        row = conn.execute("SELECT preferences FROM users WHERE telegram_id = %s", (uid,)).fetchone()
    try:
        return Preferences.model_validate(row[0] if row and row[0] else {})
    except Exception:
        return Preferences()


def update_preferences(uid, updates: dict) -> Preferences:
    """Merge validated updates into stored preferences. Unknown keys are ignored."""
    allowed = Preferences.model_fields
    clean = {k: v for k, v in updates.items() if k in allowed}
    merged = {**get_preferences(uid).model_dump(), **clean}
    new = Preferences.model_validate(merged)  # raises if a value is invalid
    with get_conn() as conn:
        conn.execute(
            "UPDATE users SET preferences = %s::jsonb WHERE telegram_id = %s",
            (new.model_dump_json(), uid),
        )
    return new


def record_matches(uid, jobs, source, reasons):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO matches (telegram_id, job_id, source, reason) VALUES (%s, %s, %s, %s)",
                [(uid, j["id"], source, r) for j, r in zip(jobs, reasons)],
            )


def shown_job_ids(uid):
    with get_conn() as conn:
        rows = conn.execute("SELECT DISTINCT job_id FROM matches WHERE telegram_id = %s", (uid,)).fetchall()
    return {r[0] for r in rows}


def recent_matches(uid, n=3):
    """The last n jobs shown to the user, oldest first (so position 1 is the first card)."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT j.id, j.title, j.company_name, j.location, j.description "
            "FROM matches m JOIN jobs j ON j.id = m.job_id "
            "WHERE m.telegram_id = %s ORDER BY m.id DESC LIMIT %s",
            (uid, n),
        ).fetchall()
    jobs = [
        {"id": r[0], "title": r[1], "company_name": r[2], "location": r[3], "description": r[4] or ""}
        for r in rows
    ]
    return list(reversed(jobs))


def record_feedback(uid, job_id, vote):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO feedback (telegram_id, job_id, vote) VALUES (%s, %s, %s) "
            "ON CONFLICT (telegram_id, job_id) DO UPDATE SET vote = EXCLUDED.vote, created_at = now()",
            (uid, job_id, vote),
        )


def feedback_counts(uid):
    with get_conn() as conn:
        row = conn.execute(
            "SELECT count(*) FILTER (WHERE vote = 1), count(*) FILTER (WHERE vote = -1) "
            "FROM feedback WHERE telegram_id = %s",
            (uid,),
        ).fetchone()
    return row[0], row[1]


def feedback_vectors(uid, limit=20):
    """Embeddings of recently liked and disliked jobs."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT f.vote, j.embedding::text FROM feedback f JOIN jobs j ON j.id = f.job_id "
            "WHERE f.telegram_id = %s AND j.embedding IS NOT NULL "
            "ORDER BY f.created_at DESC LIMIT %s",
            (uid, limit),
        ).fetchall()
    liked = [json.loads(e) for v, e in rows if v == 1]
    disliked = [json.loads(e) for v, e in rows if v == -1]
    return liked, disliked


def disliked_companies(uid, min_count=2):
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT lower(j.company_name) FROM feedback f JOIN jobs j ON j.id = f.job_id "
            "WHERE f.telegram_id = %s AND f.vote = -1 "
            "GROUP BY 1 HAVING count(*) >= %s",
            (uid, min_count),
        ).fetchall()
    return {r[0] for r in rows if r[0]}


def personalise(base_vec, liked, disliked, w_like=0.6, w_dislike=0.3):
    """Rocchio relevance feedback: move the query toward liked jobs, away from disliked."""
    q = np.array(base_vec, dtype=float)
    if liked:
        q = q + w_like * np.mean(liked, axis=0)
    if disliked:
        q = q - w_dislike * np.mean(disliked, axis=0)
    norm = np.linalg.norm(q)
    return (q / norm).tolist() if norm else list(base_vec)