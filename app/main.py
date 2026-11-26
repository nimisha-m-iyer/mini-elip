"""FastAPI app. In production it also hosts the Telegram webhook."""
import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query, Request
from telegram import Update

from app.config import settings
from app.db import get_conn
from app.search import MODES, search

log = logging.getLogger("main")
tg_app = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global tg_app
    if settings.webhook_base_url:
        from app.bot import _warmup, build_application
        tg_app = build_application(with_warmup=False)
        await tg_app.initialize()
        await tg_app.start()
        await tg_app.bot.set_webhook(
            url=f"{settings.webhook_base_url.rstrip('/')}/telegram/webhook",
            secret_token=settings.telegram_webhook_secret or None,
            allowed_updates=Update.ALL_TYPES,
            drop_pending_updates=True,
        )
        log.info("webhook set")
        # Load models in the background so the port opens right away.
        asyncio.create_task(asyncio.to_thread(_warmup))
    yield
    if tg_app:
        await tg_app.stop()
        await tg_app.shutdown()


app = FastAPI(title="mini-elip", lifespan=lifespan)


@app.get("/healthz")
def healthz():
    """Cheap liveness check. Does not touch the database, so pinging it
    will not keep Neon awake or use up its free compute hours."""
    return {"status": "ok"}


@app.get("/health")
def health():
    """Deep check: also verifies the database and pgvector."""
    status = {"status": "ok", "db": False, "pgvector": False}
    try:
        with get_conn() as conn:
            conn.execute("SELECT 1")
            status["db"] = True
            row = conn.execute("SELECT 1 FROM pg_extension WHERE extname = 'vector'").fetchone()
            status["pgvector"] = row is not None
    except Exception as e:
        status["status"] = "error"
        status["error"] = str(e)
    return status


@app.post("/telegram/webhook")
async def telegram_webhook(request: Request):
    if tg_app is None:
        raise HTTPException(503, "webhook not enabled")
    secret = settings.telegram_webhook_secret
    if secret and request.headers.get("x-telegram-bot-api-secret-token") != secret:
        raise HTTPException(403, "bad secret")
    update = Update.de_json(await request.json(), tg_app.bot)
    await tg_app.update_queue.put(update)
    return {"ok": True}


@app.get("/search")
def search_endpoint(
    q: str = Query(..., min_length=2, max_length=500),
    mode: str = "hybrid_rerank",
    k: int = Query(10, ge=1, le=50),
    remote_only: bool = False,
    location: str | None = None,
):
    if mode not in MODES:
        raise HTTPException(400, f"mode must be one of {MODES}")
    jobs = search(q, mode=mode, k=k, remote_only=remote_only, location=location)
    for j in jobs:
        j["description"] = j["description"][:300]
    return {"query": q, "mode": mode, "count": len(jobs), "results": jobs}