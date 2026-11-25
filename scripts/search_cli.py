"""Try the search from the terminal.
Usage:
  python -m scripts.search_cli "python backend engineer"
  python -m scripts.search_cli "python backend engineer" --mode vector --k 5
  python -m scripts.search_cli "data analyst" --remote
  python -m scripts.search_cli "kubernetes platform engineer" --compare
"""
import argparse
import time

from app.search import MODES, search


def show(jobs):
    for i, j in enumerate(jobs, 1):
        remote = " [remote]" if j["remote"] else ""
        print(f"  {i:>2}. {j['title'][:60]} | {j['company_name']} | {j['location'][:30]}{remote}")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("query")
    p.add_argument("--mode", default="hybrid_rerank", choices=MODES)
    p.add_argument("--k", type=int, default=8)
    p.add_argument("--remote", action="store_true")
    p.add_argument("--location")
    p.add_argument("--compare", action="store_true", help="run all four modes")
    a = p.parse_args()

    modes = MODES if a.compare else (a.mode,)
    for m in modes:
        t0 = time.time()
        jobs = search(a.query, mode=m, k=a.k, remote_only=a.remote, location=a.location)
        print(f"\n== {m}  ({time.time() - t0:.2f}s) ==")
        show(jobs)


if __name__ == "__main__":
    main()