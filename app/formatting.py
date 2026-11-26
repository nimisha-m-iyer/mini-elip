"""Text and button layout shared by the bot and the daily digest script."""


def format_job(i, job, reason):
    remote = " (remote)" if job.get("remote") else ""
    loc = job.get("location") or "Location not listed"
    lines = [f"{i}. {job['title']}", f"{job['company_name']} - {loc}{remote}"]
    if reason:
        lines.append(f"Why: {reason}")
    if job.get("url"):
        lines.append(job["url"])
    return "\n".join(lines)


def feedback_buttons(job_id):
    """Rows of {text, callback_data}. callback_data is 'fb:<job_id>:<vote>'."""
    return [[
        {"text": "👍 Relevant", "callback_data": f"fb:{job_id}:1"},
        {"text": "👎 Not for me", "callback_data": f"fb:{job_id}:-1"},
    ]]