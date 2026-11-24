"""Embed only jobs that have no embedding yet (new or changed).
Safe to stop with Ctrl+C and re-run: progress is saved after every batch.
Usage: python -m scripts.embed
"""
import logging

from app.db import get_conn
from app.embeddings import embed_texts, to_pgvector

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("embed")

BATCH = 32
PENDING = "embedding IS NULL AND expired_at IS NULL"


def job_text(title, company_name, location, description):
    return f"{title} at {company_name}. Location: {location}. {(description or '')[:2000]}"


def main():
    with get_conn() as conn:
        total = conn.execute(f"SELECT count(*) FROM jobs WHERE {PENDING}").fetchone()[0]
        log.info("%d jobs need embedding", total)
        done = 0
        while True:
            rows = conn.execute(
                f"SELECT id, title, company_name, location, description FROM jobs "
                f"WHERE {PENDING} ORDER BY id LIMIT %s",
                (BATCH,),
            ).fetchall()
            if not rows:
                break
            vectors = embed_texts([job_text(*r[1:]) for r in rows])
            for r, vec in zip(rows, vectors):
                conn.execute(
                    "UPDATE jobs SET embedding = %s::vector WHERE id = %s",
                    (to_pgvector(vec), r[0]),
                )
            conn.commit()
            done += len(rows)
            log.info("embedded %d / %d", done, total)
    log.info("DONE")


if __name__ == "__main__":
    main()