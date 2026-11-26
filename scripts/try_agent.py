"""Chat with the agent from the terminal.
Usage: python -m scripts.try_agent "show me jobs"
Uses a fake local user (id 999). The first run parses data/resume.pdf and saves the profile.
"""
import logging
import sys
from pathlib import Path

from app import users
from app.agent import run_agent
from app.formatting import format_job
from app.profile import Profile, extract_pdf_text, parse_resume_text

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
UID = 999


def main():
    if len(sys.argv) < 2:
        print('Usage: python -m scripts.try_agent "your message"')
        return
    users.upsert_user(UID, "cli_test")
    stored = users.get_profile(UID)
    if stored:
        profile = Profile.model_validate(stored)
    else:
        profile = parse_resume_text(extract_pdf_text(Path("data/resume.pdf").read_bytes()))
        users.save_profile(UID, profile.model_dump_json())
    reply, cards = run_agent(UID, profile, " ".join(sys.argv[1:]))
    print("\nBOT:", reply)
    for i, (job, reason) in enumerate(cards, 1):
        print("\n" + format_job(i, job, reason))


if __name__ == "__main__":
    main()