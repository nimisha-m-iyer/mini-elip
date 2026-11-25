"""Telegram bot v1 (polling mode, for local use). Phase 5 switches to webhooks."""
import asyncio
import logging

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

from app import users
from app.config import settings
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
    "Send me your resume as a PDF and I'll find 3 jobs that fit.\n\n"
    "Privacy: the text of your resume is sent to an AI provider (Groq) to extract your "
    "skills. I store the extracted profile (name, skills, education, experience summary), "
    "not your PDF. Use /delete to erase everything.\n\n"
    "Commands: /matches (new matches from your saved profile), /delete, /help"
)


def format_profile(p: Profile):
    skills = ", ".join(p.skills[:10]) or "none found"
    roles = ", ".join(p.roles_wanted) or "none found"
    return (
        "Here is what I understood from your resume:\n"
        f"- Headline: {p.headline}\n- Level: {p.seniority}\n"
        f"- Skills: {skills}\n- Fits roles like: {roles}\n"
    )


def format_matches(jobs):
    lines = ["Your top matches:\n"]
    for i, j in enumerate(jobs, 1):
        remote = " (remote)" if j["remote"] else ""
        lines.append(f"{i}. {j['title']}\n   {j['company_name']} - {j['location']}{remote}\n   {j['url']}\n")
    return "\n".join(lines)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    await run(users.upsert_user, u.id, u.username)
    await run(users.log_event, u.id, "start")
    await update.message.reply_text(WELCOME)


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(WELCOME)


async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Please send your resume as a PDF file. If you already did, try /matches."
    )


async def send_matches(message, profile: Profile, uid: int):
    jobs = await run(match_for_profile, profile)
    if not jobs:
        await message.reply_text("I could not find matches right now. Please try again later.")
        return
    await run(users.log_event, uid, "matches_shown", {"count": len(jobs)})
    await message.reply_text(format_matches(jobs), disable_web_page_preview=True)


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


async def matches_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    stored = await run(users.get_profile, u.id)
    if not stored:
        await update.message.reply_text("I do not have your resume yet. Send it as a PDF first.")
        return
    await send_matches(update.message, Profile.model_validate(stored), u.id)


async def delete_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await run(users.delete_user, update.effective_user.id)
    await update.message.reply_text("Done. Your profile and activity history are deleted.")


async def on_error(update, context: ContextTypes.DEFAULT_TYPE):
    log.error("unhandled error", exc_info=context.error)
    if isinstance(update, Update) and update.effective_message:
        await update.effective_message.reply_text("Something went wrong on my side. Please try again.")


def _warmup():
    from app.embeddings import embed_texts
    from app.search import rerank_scores
    embed_texts(["warm up"])
    rerank_scores("warm up", [{"title": "t", "company_name": "c", "location": "l", "description": "d"}])


async def post_init(app: Application):
    await run(_warmup)  # load both models once, so the first user is not slow
    log.info("models warmed up, bot is ready")


def main():
    if not settings.telegram_bot_token:
        raise SystemExit("TELEGRAM_BOT_TOKEN is empty. Put it in .env and recreate the bot container.")
    app = Application.builder().token(settings.telegram_bot_token).post_init(post_init).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("matches", matches_cmd))
    app.add_handler(CommandHandler("delete", delete_cmd))
    app.add_handler(MessageHandler(filters.Document.ALL, on_document))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    app.add_error_handler(on_error)
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()