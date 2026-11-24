import html
from datetime import datetime, timezone

import httpx
from bs4 import BeautifulSoup
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

HEADERS = {"User-Agent": "mini-elip-portfolio-project/0.1"}


def clean_html(raw):
    """HTML (possibly entity-escaped) -> plain text."""
    if not raw:
        return ""
    text = BeautifulSoup(html.unescape(raw), "html.parser").get_text(" ", strip=True)
    return " ".join(text.split())


def parse_dt(value):
    """ISO string or epoch-milliseconds -> datetime (or None)."""
    if not value:
        return None
    try:
        if isinstance(value, (int, float)):
            return datetime.fromtimestamp(value / 1000, tz=timezone.utc)
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (ValueError, OSError):
        return None


# Retry network errors, timeouts, 429 and 5xx with exponential backoff (1s, 2s, 4s...).
# A 404 is NOT retried: retrying will not make a missing board appear.
@retry(
    stop=stop_after_attempt(4),
    wait=wait_exponential(multiplier=1, min=1, max=10),
    retry=retry_if_exception_type(httpx.TransportError),
    reraise=True,
)
def get_json(url, params=None):
    r = httpx.get(url, params=params, headers=HEADERS, timeout=30, follow_redirects=True)
    if r.status_code == 429 or r.status_code >= 500:
        raise httpx.TransportError(f"retryable status {r.status_code} from {url}")
    r.raise_for_status()
    return r.json()


def make_job(source, company, external_id, title, company_name, location,
             remote, url, description, posted_at):
    return {
        "source": source,
        "company": company,
        "external_id": str(external_id),
        "title": (title or "").strip(),
        "company_name": company_name or company,
        "location": (location or "").strip(),
        "remote": bool(remote),
        "url": url,
        "description": description or "",
        "posted_at": posted_at,
    }


def fetch_greenhouse(slug):
    data = get_json(
        f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs",
        params={"content": "true"},
    )
    jobs = []
    for j in data.get("jobs", []):
        location = (j.get("location") or {}).get("name") or ""
        jobs.append(make_job(
            "greenhouse", slug, j["id"], j.get("title"), j.get("company_name"),
            location, "remote" in location.lower(), j.get("absolute_url"),
            clean_html(j.get("content")),
            parse_dt(j.get("first_published") or j.get("updated_at")),
        ))
    return jobs


def fetch_lever(slug):
    data = get_json(f"https://api.lever.co/v0/postings/{slug}", params={"mode": "json"})
    if not isinstance(data, list):
        raise ValueError(f"unexpected Lever response: {str(data)[:100]}")
    jobs = []
    for j in data:
        cats = j.get("categories") or {}
        location = cats.get("location") or ""
        parts = [j.get("descriptionPlain") or ""]
        for block in j.get("lists") or []:
            parts.append((block.get("text") or "") + " " + clean_html(block.get("content")))
        parts.append(j.get("additionalPlain") or "")
        remote = (j.get("workplaceType") == "remote") or ("remote" in location.lower())
        jobs.append(make_job(
            "lever", slug, j["id"], j.get("text"), slug, location, remote,
            j.get("hostedUrl"), " ".join(p for p in parts if p).strip(),
            parse_dt(j.get("createdAt")),
        ))
    return jobs


def fetch_ashby(slug):
    data = get_json(f"https://api.ashbyhq.com/posting-api/job-board/{slug}")
    jobs = []
    for j in data.get("jobs", []):
        if j.get("isListed") is False:
            continue
        location = j.get("location") or ""
        jobs.append(make_job(
            "ashby", slug, j["id"], j.get("title"), slug, location,
            j.get("isRemote") or "remote" in location.lower(),
            j.get("jobUrl") or j.get("applyUrl"),
            j.get("descriptionPlain") or clean_html(j.get("descriptionHtml")),
            parse_dt(j.get("publishedAt")),
        ))
    return jobs


FETCHERS = {
    "greenhouse": fetch_greenhouse,
    "lever": fetch_lever,
    "ashby": fetch_ashby,
}