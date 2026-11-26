"""Profile -> top job matches."""
import logging

from app.profile import Profile, profile_to_query
from app.search import search

log = logging.getLogger("matching")

INDIA_TERMS = [
    "india", "bengaluru", "bangalore", "hyderabad", "mumbai", "pune",
    "delhi", "gurugram", "gurgaon", "noida", "chennai", "kolkata",
]
# If the candidate's profile mentions any of these, we treat them as India-based.
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


def match_for_profile(profile: Profile, n=3):
    exclude_senior = profile.seniority in ("intern", "junior")
    query = profile_to_query(profile)
    locs = preferred_locations(profile)

    jobs = []
    if locs:
        jobs = pick_top(
            search(query, mode="hybrid_rerank", k=15, exclude_senior=exclude_senior, locations=locs), n
        )
    if len(jobs) < n:
        # Not enough local jobs: fall back to anywhere, and log it so we can measure coverage.
        log.info("location filter gave %d jobs, falling back to unfiltered search", len(jobs))
        extra = pick_top(search(query, mode="hybrid_rerank", k=15, exclude_senior=exclude_senior), n)
        seen = {j["id"] for j in jobs}
        jobs += [j for j in extra if j["id"] not in seen][: n - len(jobs)]
    return jobs
