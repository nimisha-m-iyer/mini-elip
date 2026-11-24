"""Look at one board without touching the database.
Usage: python -m scripts.peek greenhouse airbnb
"""
import sys

from app.fetchers import FETCHERS


def main():
    if len(sys.argv) != 3 or sys.argv[1] not in FETCHERS:
        print("Usage: python -m scripts.peek <greenhouse|lever|ashby> <slug>")
        return
    source, slug = sys.argv[1], sys.argv[2]
    jobs = FETCHERS[source](slug)
    print(f"{source}/{slug}: {len(jobs)} jobs\n")
    for j in jobs[:5]:
        print(f"- {j['title']} | {j['location']} | remote={j['remote']} | posted={j['posted_at']}")
        print(f"  {j['url']}")
    if jobs:
        print("\nFirst description (first 400 chars):")
        print(jobs[0]["description"][:400])


if __name__ == "__main__":
    main()