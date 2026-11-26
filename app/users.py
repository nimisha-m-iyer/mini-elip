"""Database helpers for users and usage events."""
import json

from app.db import get_conn


def upsert_user(telegram_id, username):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO users (telegram_id, username) VALUES (%s, %s) "
            "ON CONFLICT (telegram_id) DO UPDATE "
            "SET username = EXCLUDED.username, last_active_at = now()",
            (telegram_id, username),
        )


def save_profile(telegram_id, profile_json):
    with get_conn() as conn:
        conn.execute(
            "UPDATE users SET profile = %s::jsonb, last_active_at = now() WHERE telegram_id = %s",
            (profile_json, telegram_id),
        )


def get_profile(telegram_id):
    """Return the stored profile as a dict, or None."""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT profile FROM users WHERE telegram_id = %s", (telegram_id,)
        ).fetchone()
    return row[0] if row else None


def log_event(telegram_id, kind, detail=None):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO events (telegram_id, kind, detail) VALUES (%s, %s, %s::jsonb)",
            (telegram_id, kind, json.dumps(detail or {})),
        )


def set_digest(telegram_id, enabled):
    with get_conn() as conn:
        conn.execute(
            "UPDATE users SET digest_enabled = %s WHERE telegram_id = %s", (enabled, telegram_id)
        )


def get_digest(telegram_id):
    with get_conn() as conn:
        row = conn.execute(
            "SELECT digest_enabled FROM users WHERE telegram_id = %s", (telegram_id,)
        ).fetchone()
    return bool(row and row[0])


def delete_user(telegram_id):
    with get_conn() as conn:
        conn.execute("DELETE FROM feedback WHERE telegram_id = %s", (telegram_id,))
        conn.execute("DELETE FROM matches WHERE telegram_id = %s", (telegram_id,))
        conn.execute("DELETE FROM events WHERE telegram_id = %s", (telegram_id,))
        conn.execute("DELETE FROM users WHERE telegram_id = %s", (telegram_id,))