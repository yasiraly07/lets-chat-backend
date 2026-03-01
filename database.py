"""
Thin async wrapper around the Supabase Python client for persisting
rooms and messages to Postgres.
"""
import logging
from datetime import datetime, timezone
from typing import Any

from supabase import AsyncClient, acreate_client

from config import settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Client lifecycle
# ---------------------------------------------------------------------------

_client: AsyncClient | None = None


async def get_client() -> AsyncClient:
    global _client
    if _client is None:
        _client = await acreate_client(settings.supabase_url, settings.supabase_key)
    return _client


async def close_client():
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


# ---------------------------------------------------------------------------
# Rooms
# ---------------------------------------------------------------------------

async def persist_room(room_id: str, created_at: str, max_users: int = 50) -> bool:
    """Insert a room record. Returns True on success."""
    try:
        db = await get_client()
        await db.table("rooms").insert({
            "room_id": room_id,
            "created_at": created_at,
            "max_users": max_users,
        }).execute()
        return True
    except Exception:
        logger.exception("Failed to persist room %s", room_id)
        return False


async def room_exists_in_db(room_id: str) -> dict | None:
    """Return the room row if it exists, else None."""
    try:
        db = await get_client()
        res = await db.table("rooms").select("*").eq("room_id", room_id).maybe_single().execute()
        return res.data
    except Exception:
        logger.exception("Failed to query room %s", room_id)
        return None


# ---------------------------------------------------------------------------
# Messages
# ---------------------------------------------------------------------------

async def persist_message(msg: dict) -> bool:
    """
    Persist a chat or system message row.
    ``msg`` is the same dict that gets broadcast to clients.
    """
    try:
        db = await get_client()
        row: dict[str, Any] = {
            "message_id": msg.get("message_id") or msg.get("type", "system") + "-" + msg.get("timestamp", ""),
            "room_id": msg["room_id"],
            "user_id": msg.get("user_id", "system"),
            "username": msg.get("username", "system"),
            "content": msg["content"],
            "type": msg.get("type", "message"),
            "timestamp": msg.get("timestamp", datetime.now(timezone.utc).isoformat()),
        }
        await db.table("messages").insert(row).execute()
        return True
    except Exception:
        logger.exception("Failed to persist message for room %s", msg.get("room_id"))
        return False


async def is_username_taken_in_room(room_id: str, username: str) -> bool:
    """
    Return True if this username has ever posted a message in the room.
    Used as a DB-level uniqueness gate that survives server restarts.
    """
    try:
        db = await get_client()
        res = (
            await db.table("messages")
            .select("message_id")
            .eq("room_id", room_id)
            .eq("username", username)
            .neq("type", "system")
            .limit(1)
            .execute()
        )
        return bool(res.data)
    except Exception:
        logger.exception("Failed to check username '%s' in room %s", username, room_id)
        return False  # fail open — in-memory check still applies


async def load_recent_messages(room_id: str, limit: int = 50) -> list[dict]:
    """Load the N most recent messages for a room from Postgres."""
    try:
        db = await get_client()
        # Fetch newest N rows (desc), then reverse so oldest-first for display
        res = (
            await db.table("messages")
            .select("message_id, room_id, user_id, username, content, type, timestamp")
            .eq("room_id", room_id)
            .order("timestamp", desc=True)
            .limit(limit)
            .execute()
        )
        rows = list(reversed(res.data or []))
        # Normalise to the same shape the WS layer uses
        return [
            {
                "type": r["type"],
                "message_id": r["message_id"],
                "room_id": r["room_id"],
                "user_id": r["user_id"],
                "username": r["username"],
                "content": r["content"],
                "timestamp": r["timestamp"],
            }
            for r in rows
        ]
    except Exception:
        logger.exception("Failed to load messages for room %s", room_id)
        return []
