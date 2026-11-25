"""Profile -> top job matches."""
from app.profile import Profile, profile_to_query
from app.search import search


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
    # Early-career candidates should not be shown Staff/Senior/Lead roles.
    exclude_senior = profile.seniority in ("intern", "junior")
    jobs = search(
        profile_to_query(profile), mode="hybrid_rerank", k=15, exclude_senior=exclude_senior
    )
    return pick_top(jobs, n)