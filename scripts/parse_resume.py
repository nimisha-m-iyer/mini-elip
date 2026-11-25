"""Parse a resume PDF and show matching jobs.
Usage: python -m scripts.parse_resume data/resume.pdf
"""
import logging
import sys
import time
from pathlib import Path

from app.profile import extract_pdf_text, parse_resume_text, profile_to_query
from app.search import search

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


def main():
    if len(sys.argv) != 2:
        print("Usage: python -m scripts.parse_resume <path-to-pdf>")
        return
    text = extract_pdf_text(Path(sys.argv[1]).read_bytes())
    print(f"\nExtracted {len(text)} characters. First 300:\n{text[:300]}\n")

    t0 = time.time()
    profile = parse_resume_text(text)
    print(f"\nProfile parsed in {time.time() - t0:.1f}s:\n")
    print(profile.model_dump_json(indent=2))

    query = profile_to_query(profile)
    print(f"\nSearch query: {query}\n")
    t0 = time.time()
    jobs = search(query, mode="hybrid_rerank", k=5)
    print(f"Top matches ({time.time() - t0:.1f}s):")
    for i, j in enumerate(jobs, 1):
        print(f"  {i}. {j['title'][:60]} | {j['company_name']} | {j['location'][:30]}")
        print(f"     {j['url']}")


if __name__ == "__main__":
    main()