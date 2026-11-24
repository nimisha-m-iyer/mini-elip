"""Fetch every board, then sync into Postgres.
Usage: python -m scripts.ingest
"""
import hashlib
import logging
import re
import time

from app.db import get_conn
from app.fetchers import FETCHERS
from app.sources import BOARDS

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("ingest")

INSERT_SQL = """
INSERT INTO jobs (source, company, external_id, title, company_name, location, remote,
                  url, description, posted_at, content_hash, dedupe_key)
VALUES (%(source)s, %(company)s, %(external_id)s, %(title)s, %(company_name)s, %(location)s,
        %(remote)s, %(url)s, %(description)s, %(posted_at)s, %(content_hash)s, %(dedupe_key)s)
"""

UPDATE_SQL = """
UPDATE jobs SET title = %(title)s, company_name = %(company_name)s, location = %(location)s,
    remote = %(remote)s, url = %(url)s, description = %(description)s,
    posted_at = %(posted_at)s, content_hash = %(content_hash)s, dedupe_key = %(dedupe_key)s,
    embedding = NULL,              -- content changed, so it must be re-embedded
    last_seen_at = now(), expired_at = NULL
WHERE source = %(source)s AND company = %(company)s AND external_id = %(external_id)s
"""


def make_content_hash(job):
    raw = f"{job['title']}|{job['location']}|{job['description']}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def make_dedupe_key(job):
    raw = f"{job['company_name']} {job['title']} {job['location']}".lower()
    return hashlib.sha1(re.sub(r"[^a-z0-9]+", " ", raw).strip().encode("utf-8")).hexdigest()


def sync_board(conn, source, slug, jobs):
    stats = {"new": 0, "changed": 0, "unchanged": 0, "expired": 0}

    # Dedupe inside this fetch: the same external_id twice -> keep the last one.
    by_id = {j["external_id"]: j for j in jobs}

    existing = {
        row[0]: row[1]
        for row in conn.execute(
            "SELECT external_id, content_hash FROM jobs WHERE source = %s AND company = %s",
            (source, slug),
        )
    }

    unchanged_ids = []
    for ext_id, job in by_id.items():
        job["content_hash"] = make_content_hash(job)
        job["dedupe_key"] = make_dedupe_key(job)
        if ext_id not in existing:
            conn.execute(INSERT_SQL, job)
            stats["new"] += 1
        elif existing[ext_id] != job["content_hash"]:
            conn.execute(UPDATE_SQL, job)
            stats["changed"] += 1
        else:
            unchanged_ids.append(ext_id)
            stats["unchanged"] += 1

    if unchanged_ids:
        conn.execute(
            "UPDATE jobs SET last_seen_at = now(), expired_at = NULL "
            "WHERE source = %s AND company = %s AND external_id = ANY(%s)",
            (source, slug, unchanged_ids),
        )

    # Expire jobs that vanished from the board. Safety guard: an empty response while we
    # hold many jobs is more likely an API glitch than every job being removed.
    if not by_id and existing:
        log.warning("%s/%s returned 0 jobs but DB has %d. Not expiring.", source, slug, len(existing))
    else:
        cur = conn.execute(
            "UPDATE jobs SET expired_at = now() "
            "WHERE source = %s AND company = %s AND expired_at IS NULL "
            "AND NOT (external_id = ANY(%s))",
            (source, slug, list(by_id.keys())),
        )
        stats["expired"] = cur.rowcount
    return stats


def main():
    totals = {"new": 0, "changed": 0, "unchanged": 0, "expired": 0}
    ok, failed = 0, 0
    with get_conn() as conn:
        for source, slug in BOARDS:
            try:
                jobs = FETCHERS[source](slug)
            except Exception as e:  # one dead board must not stop the run
                log.warning("SKIP %s/%s: %s", source, slug, e)
                failed += 1
                continue
            stats = sync_board(conn, source, slug, jobs)
            conn.commit()  # save progress after every board
            ok += 1
            for k in totals:
                totals[k] += stats[k]
            log.info("%s/%s fetched=%d %s", source, slug, len(jobs), stats)
            time.sleep(0.5)  # be polite to public APIs
    log.info("DONE boards_ok=%d boards_failed=%d totals=%s", ok, failed, totals)


if __name__ == "__main__":
    main()