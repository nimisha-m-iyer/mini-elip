"""Telegram bot: resume upload, matches with 👍/👎, preferences, agent chat, digest opt-in.
Local dev uses polling (main). Production uses the webhook in app/main.py."""
import asyncio
import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (Application, CallbackQueryHandler, CommandHandler, ContextTypes,
                          MessageHandler, filters)

from app import memory, users
from app.agent import run_agent
from app.config import settings
from app.explain import explain_jobs
from app.formatting import feedback_buttons, format_job
from app.llm import LLMError
from app.matching import match_for_profile
from app.profile import Profile, ProfileParseError, extract_pdf_text, parse_resume_text

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
# httpx logs full request URLs at INFO, and Telegram URLs contain the bot token.
logging.getLogger("httpx").setLevel(logging.WARNING)
log = logging.getLogger("bot")

MAX_PDF_BYTES = 5 * 1024 * 1024
run = asyncio.to_thread  # run blocking code (DB, LLM, search) without freezing the bot

WELCOME = (
    "Hi! I'm a job-matching bot (a portfolio project).\n\n"
    "Send your resume as a PDF (or paste its text) and I'll find 3 jobs that fit. "
    "Tap 👍/👎 on each match and I'll learn what you like. You can also just chat, e.g. "
    "\"only remote jobs\" or \"why does the first one fit me?\".\n\n"
    "Privacy: the text of your resume is sent to an AI provider (Groq) to extract your skills. "
    "I store the extracted profile, your preferences, the jobs I showed you and your 👍/👎, "
    "not your PDF. /delete erases everything.\n\n"
    "Commands: /matches, /settings, /digest on|off (a daily message with 3 matches), /delete, /help"
)


def format_profile(p: Profile):
    skills = ", ".join(p.skills[:10]) or "none found"
    roles = ", ".join(p.roles_wanted) or "none found"
    return (
        "Here is what I understood from your resume:\n"
        f"- Headline: {p.headline}\n- Level: {p.seniority}\n"
        f"- Skills: {skills}\n- Fits roles like: {roles}\n"
    )


def keyboard(job_id):
    rows = feedback_buttons(job_id)
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton(b["text"], callback_data=b["callback_data"]) for b in row] for row in rows]
    )


async def send_cards(message, cards):
    for i, (job, reason) in enumerate(cards, 1):
        await message.reply_text(
            format_job(i, job, reason), reply_markup=keyboard(job["id"]), disable_web_page_preview=True
        )


async def send_matches(message, profile: Profile, uid: int, source="manual"):
    jobs = await run(match_for_profile, profile, 3, uid)
    if not jobs:
        await message.reply_text(
            "No new matches right now. I only show jobs you have not seen yet. "
            "Try again after tomorrow's update, or adjust your preferences (/settings)."
        )
        return
    reasons = await run(explain_jobs, profile, jobs)
    await run(memory.record_matches, uid, jobs, source, reasons)
    await run(users.log_event, uid, "matches_shown", {"count": len(jobs), "source": source})
    await message.reply_text("Your top matches (tap 👍 or 👎 so I can learn what you like):")
    await send_cards(message, list(zip(jobs, reasons)))


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    await run(users.upsert_user, u.id, u.username)
    await run(users.log_event, u.id, "start")
    await update.message.reply_text(WELCOME)


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(WELCOME)


async def process_resume(msg, u, text):
    try:
        profile = await run(parse_resume_text, text)
    except ProfileParseError as e:
        await run(users.log_event, u.id, "resume_failed", {"reason": "parse"})
        await msg.reply_text(f"I could not read that resume: {e}")
        return
    except LLMError:
        log.exception("LLM failure")
        await run(users.log_event, u.id, "resume_failed", {"reason": "llm"})
        await msg.reply_text("My AI service had a problem. Please try again in a minute.")
        return
    await run(users.save_profile, u.id, profile.model_dump_json())
    await run(users.log_event, u.id, "resume_ok")
    await msg.reply_text(format_profile(profile))
    await send_matches(msg, profile, u.id)


async def on_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg, u = update.message, update.effective_user
    doc = msg.document
    is_pdf = doc.mime_type == "application/pdf" or (doc.file_name or "").lower().endswith(".pdf")
    if not is_pdf:
        await msg.reply_text("Please send your resume as a PDF file.")
        return
    if doc.file_size and doc.file_size > MAX_PDF_BYTES:
        await msg.reply_text("That file is over 5 MB. Please send a smaller PDF.")
        return
    await run(users.upsert_user, u.id, u.username)
    await msg.reply_text("Got it. Reading your resume, this takes about 20 seconds...")
    try:
        tg_file = await doc.get_file()
        data = bytes(await tg_file.download_as_bytearray())
        text = await run(extract_pdf_text, data)
    except ProfileParseError as e:
        await run(users.log_event, u.id, "resume_failed", {"reason": "pdf"})
        await msg.reply_text(f"I could not read that resume: {e}")
        return
    await process_resume(msg, u, text)


async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg, u = update.message, update.effective_user
    text = msg.text.strip()
    await run(users.upsert_user, u.id, u.username)
    if len(text) > 800:  # long text = a pasted resume
        await msg.reply_text("That looks like resume text. Reading it, about 20 seconds...")
        await process_resume(msg, u, text)
        return
    stored = await run(users.get_profile, u.id)
    if not stored:
        await msg.reply_text("Please send your resume as a PDF first (or paste its text). Then we can chat.")
        return
    try:
        reply, cards = await run(run_agent, u.id, Profile.model_validate(stored), text)
    except LLMError:
        log.exception("agent LLM failure")
        await msg.reply_text("My AI service had a problem. Please try again in a minute.")
        return
    await run(users.log_event, u.id, "agent_chat", {"cards": len(cards)})
    await msg.reply_text(reply)
    await send_cards(msg, cards)


async def on_feedback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    try:
        _, job_id, vote = q.data.split(":")
        job_id, vote = int(job_id), int(vote)
        if vote not in (1, -1):
            raise ValueError
    except ValueError:
        await q.answer("Unknown button")
        return
    uid = q.from_user.id
    await run(memory.record_feedback, uid, job_id, vote)
    await run(users.log_event, uid, "feedback", {"job_id": job_id, "vote": vote})
    await q.answer("Noted! I'll use this next time." if vote == 1 else "Got it, fewer like this.")
    label = "👍 You liked this" if vote == 1 else "👎 Not for you"
    await q.edit_message_reply_markup(
        InlineKeyboardMarkup([[InlineKeyboardButton(label, callback_data=f"fb:{job_id}:{vote}")]])
    )


async def matches_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    stored = await run(users.get_profile, u.id)
    if not stored:
        await update.message.reply_text("I do not have your resume yet. Send it as a PDF first.")
        return
    await send_matches(update.message, Profile.model_validate(stored), u.id)


async def settings_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    prefs = await run(memory.get_preferences, uid)
    likes, dislikes = await run(memory.feedback_counts, uid)
    digest = await run(users.get_digest, uid)
    await update.message.reply_text(
        "Your settings:\n"
        f"- Remote only: {'yes' if prefs.remote_only else 'no'}\n"
        f"- Locations: {', '.join(prefs.locations) or 'automatic'}\n"
        f"- Avoid companies: {', '.join(prefs.avoid_companies) or 'none'}\n"
        f"- Focus: {prefs.focus or 'none'}\n"
        f"- Daily digest: {'on' if digest else 'off'} (change with /digest on or /digest off)\n"
        f"- Feedback so far: {likes} likes, {dislikes} dislikes\n\n"
        "Tip: just tell me, e.g. \"only remote jobs please\"."
    )


async def digest_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    arg = context.args[0].lower() if context.args else ""
    if arg not in ("on", "off"):
        await update.message.reply_text("Use /digest on or /digest off.")
        return
    await run(users.upsert_user, u.id, u.username)
    await run(users.set_digest, u.id, arg == "on")
    await run(users.log_event, u.id, "digest_toggle", {"enabled": arg == "on"})
    await update.message.reply_text(
        "Daily digest is on. You'll get 3 new matches each morning (about 9:00 IST)."
        if arg == "on" else "Daily digest is off."
    )


async def delete_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await run(users.delete_user, update.effective_user.id)
    await update.message.reply_text("Done. Your profile, feedback and activity history are deleted.")


async def on_error(update, context: ContextTypes.DEFAULT_TYPE):
    log.error("unhandled error", exc_info=context.error)
    if isinstance(update, Update) and update.effective_message:
        await update.effective_message.reply_text("Something went wrong on my side. Please try again.")


def _warmup():
    from app.embeddings import embed_texts
    embed_texts(["warm up"])
    if settings.rerank_enabled:
        from app.search import rerank_scores
        rerank_scores("warm up", [{"title": "t", "company_name": "c", "location": "l", "description": "d"}])


async def post_init(app: Application):
    await run(_warmup)  # load the models once, so the first user is not slow
    log.info("models warmed up, bot is ready")


def build_application(with_warmup=True):
    if not settings.telegram_bot_token:
        raise SystemExit("TELEGRAM_BOT_TOKEN is empty. Put it in .env and recreate the container.")
    builder = Application.builder().token(settings.telegram_bot_token).concurrent_updates(True)
    if with_warmup:
        builder = builder.post_init(post_init)
    app = builder.build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("matches", matches_cmd))
    app.add_handler(CommandHandler("settings", settings_cmd))
    app.add_handler(CommandHandler("digest", digest_cmd))
    app.add_handler(CommandHandler("delete", delete_cmd))
    app.add_handler(CallbackQueryHandler(on_feedback, pattern=r"^fb:"))
    app.add_handler(MessageHandler(filters.Document.ALL, on_document))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    app.add_error_handler(on_error)
    return app


def main():
    """Local development: polling mode."""
    build_application().run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()