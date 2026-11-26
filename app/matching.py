"""Profile + memory -> top job matches."""
import logging

from app import memory
from app.embeddings import embed_texts
from app.profile import Profile, profile_to_query
from app.search import QUERY_PREFIX, search

log = logging.getLogger("matching")

INDIA_TERMS = [
    "india", "bengaluru", "bangalore", "hyderabad", "mumbai", "pune",
    "delhi", "gurugram", "gurgaon", "noida", "chennai", "kolkata",
]
INDIA_HINTS = set(INDIA_TERMS) | {"karnataka", "kerala", "kottayam", "tamil nadu", "maharashtra", "telangana"}


def preferred_locations(profile: Profile):
    """Location terms to filter on, or None if we cannot tell where the candidate is."""
    text = " ".join(profile.locations).lower()
    if any(h in text for h in INDIA_HINTS):
        return INDIA_TERMS
    return None


def pick_top(jobs, n=3, max_per_company=2):
    """Take the best n jobs, but never more than max_per_company from one company."""
    picked, per_company = [], {}
    for j in jobs:
        c = j["company_name"]
        if per_company.get(c, 0) >= max_per_company:
            continue
        per_company[c] = per_company.get(c, 0) + 1
        picked.append(j)
        if len(picked) == n:
            break
    return picked


def match_for_profile(profile: Profile, n=3, uid=None, overrides=None):
    """overrides (optional): {"focus": str, "location": str, "remote_only": bool} for one search."""
    o = overrides or {}
    prefs = memory.get_preferences(uid) if uid else memory.Preferences()
    exclude_senior = profile.seniority in ("intern", "junior")

    remote_only = bool(o.get("remote_only", prefs.remote_only))
    explicit = [o["location"]] if o.get("location") else prefs.locations
    locs = explicit or (None if remote_only else preferred_locations(profile))
    strict = bool(explicit) or remote_only  # the user asked for this: never fall back to "anywhere"

    query = profile_to_query(profile)
    focus = (o.get("focus") or prefs.focus or "").strip()
    if focus:
        query += f". Especially interested in: {focus}"

    exclude_ids, avoid = [], {c.lower() for c in prefs.avoid_companies}
    qvec = None
    if uid:
        exclude_ids = list(memory.shown_job_ids(uid))
        avoid |= memory.disliked_companies(uid)
        liked, disliked = memory.feedback_vectors(uid)
        if liked or disliked:
            base = embed_texts([QUERY_PREFIX + query])[0]
            qvec = memory.personalise(base, liked, disliked)

    common = dict(
        mode="hybrid_rerank", k=15, exclude_senior=exclude_senior, remote_only=remote_only,
        query_vec=qvec, exclude_ids=exclude_ids, exclude_companies=list(avoid),
    )
    jobs = pick_top(search(query, locations=locs, **common), n)
    if locs and len(jobs) < n and not strict:
        log.info("location filter gave %d jobs, falling back to unfiltered search", len(jobs))
        extra = pick_top(search(query, **common), n)
        seen = {j["id"] for j in jobs}
        jobs += [j for j in extra if j["id"] not in seen][: n - len(jobs)]
    return jobs