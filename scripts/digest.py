"""Send the daily digest to users who opted in (/digest on). Run by GitHub Actions.
Usage: python -m scripts.digest [--dry-run]
"""
import argparse
import logging
import time

import httpx

from app import memory, users
from app.config import settings
from app.db import get_conn
from app.explain import explain_jobs
from app.formatting import feedback_buttons, format_job
from app.matching import match_for_profile
from app.profile import Profile

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)  # request URLs contain the bot token
log = logging.getLogger("digest")


def tg_send(chat_id, text, buttons=None):
    payload = {"chat_id": chat_id, "text": text, "disable_web_page_preview": True}
    if buttons:
        payload["reply_markup"] = {"inline_keyboard": buttons}
    url = f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage"
    for _ in range(4):
        r = httpx.post(url, json=payload, timeout=30)
        if r.status_code == 429:  # rate limited: wait as long as Telegram asks
            time.sleep(r.json().get("parameters", {}).get("retry_after", 3) + 1)
            continue
        return r
    return r


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="print instead of sending")
    dry = ap.parse_args().dry_run

    with get_conn() as conn:
        rows = conn.execute(
            "SELECT telegram_id, profile FROM users "
            "WHERE profile IS NOT NULL AND digest_enabled "
            "AND (last_digest_at IS NULL OR last_digest_at < now() - interval '20 hours') "
            "ORDER BY telegram_id LIMIT 200"
        ).fetchall()
    log.info("%d users due for a digest (dry_run=%s)", len(rows), dry)

    sent = skipped = failed = 0
    for uid, stored in rows:
        try:
            profile = Profile.model_validate(stored)
            jobs = match_for_profile(profile, 3, uid)
            if not jobs:
                skipped += 1
                continue
            reasons = explain_jobs(profile, jobs)
            if dry:
                print(f"\n--- user {uid} ---")
                for i, (j, r) in enumerate(zip(jobs, reasons), 1):
                    print(format_job(i, j, r), "\n")
                continue
            r = tg_send(uid, "Good morning! Here are today's 3 matches (tap 👍/👎 so I learn):")
            if r.status_code == 403:  # the user blocked the bot
                users.set_digest(uid, False)
                log.info("user blocked the bot, digest switched off")
                continue
            if r.status_code != 200:
                log.warning("sendMessage failed with status %s", r.status_code)
                failed += 1
                continue
            for i, (j, reason) in enumerate(zip(jobs, reasons), 1):
                tg_send(uid, format_job(i, j, reason), feedback_buttons(j["id"]))
            memory.record_matches(uid, jobs, "digest", reasons)
            users.log_event(uid, "digest_sent", {"count": len(jobs)})
            with get_conn() as conn:
                conn.execute("UPDATE users SET last_digest_at = now() WHERE telegram_id = %s", (uid,))
            sent += 1
            time.sleep(1)
        except Exception:
            log.exception("digest failed for one user, continuing")
            failed += 1
    log.info("DONE sent=%d skipped_no_matches=%d failed=%d", sent, skipped, failed)


if __name__ == "__main__":
    main()