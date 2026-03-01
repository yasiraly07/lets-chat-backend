import json
import logging
import re
import uuid
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query

from connection_manager import manager
import database as db

logger = logging.getLogger(__name__)

router = APIRouter(tags=["websocket"])

_ROOM_ID_RE = re.compile(r"^[A-Z0-9]{4,20}$")
_USERNAME_RE = re.compile(r"^[\w\- ]{1,32}$")  # alphanumeric, underscore, hyphen, space


@router.websocket("/ws/{room_id}")
async def websocket_endpoint(
    websocket: WebSocket,
    room_id: str,
    username: str = Query(..., min_length=1, max_length=32),
):
    """
    WebSocket endpoint for a chat room.

    Connect with:
        ws://host/ws/{ROOM_ID}?username=YourName

    Expected client messages (JSON):
        { "type": "message", "content": "Hello!" }
        { "type": "typing" }
        { "type": "ping" }

    Server message types:
        "history"      — sent once on connect with recent messages
        "system"       — user joined / left notifications
        "message"      — a chat message
        "typing"       — another user is typing (not echoed to sender)
        "pong"         — response to ping
        "error"        — something went wrong
        "rate_limited" — sender is sending too fast
    """
    room_id = room_id.strip().upper()
    username = username.strip()

    # Validate room ID format
    if not _ROOM_ID_RE.match(room_id):
        await websocket.accept()
        await websocket.send_text(json.dumps({
            "type": "error",
            "content": "Invalid room ID. Only letters and digits, 4-20 characters.",
        }))
        await websocket.close(code=4002)
        return

    # Validate username format
    if not username or not _USERNAME_RE.match(username):
        await websocket.accept()
        await websocket.send_text(json.dumps({
            "type": "error",
            "content": "Invalid username. Use letters, digits, spaces, hyphens, or underscores (1-32 chars).",
        }))
        await websocket.close(code=4002)
        return

    # Ensure room exists in memory (auto-create so bare links always work)
    if not manager.room_exists(room_id):
        row = await db.room_exists_in_db(room_id)
        if row:
            manager.create_room(room_id, max_users=row.get("max_users"))
        else:
            manager.create_room(room_id)
            await db.persist_room(room_id, manager.get_room(room_id).created_at)

    room = manager.get_room(room_id)

    # Max capacity check
    if room and room.is_full:
        await websocket.accept()
        await websocket.send_text(json.dumps({
            "type": "error",
            "content": f"Room '{room_id}' is full ({room.max_users} users max).",
        }))
        await websocket.close(code=4003)
        return

    # Duplicate username check — in-memory (currently connected) AND DB (persisted history)
    username_taken = (room and room.username_taken(username)) or (
        await db.is_username_taken_in_room(room_id, username)
    )
    if username_taken:
        await websocket.accept()
        await websocket.send_text(json.dumps({
            "type": "error",
            "content": f"Username '{username}' is already taken in this room. Please choose another.",
        }))
        await websocket.close(code=4001)
        return

    user_id = uuid.uuid4().hex

    await manager.connect(websocket, room_id, user_id, username)

    try:
        while True:
            raw = await websocket.receive_text()

            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                await websocket.send_text(json.dumps({
                    "type": "error",
                    "content": "Invalid JSON payload.",
                }))
                continue

            msg_type = data.get("type", "")

            if msg_type == "message":
                content = (data.get("content") or "").strip()
                if not content:
                    continue
                if len(content) > 4000:
                    await websocket.send_text(json.dumps({
                        "type": "error",
                        "content": "Message too long (max 4000 chars).",
                    }))
                    continue
                sent = await manager.send_chat_message(room_id, user_id, content)
                if not sent:
                    await websocket.send_text(json.dumps({
                        "type": "rate_limited",
                        "content": "You are sending messages too fast. Please slow down.",
                    }))

            elif msg_type == "typing":
                await manager.broadcast_typing(room_id, user_id)

            elif msg_type == "ping":
                await websocket.send_text(json.dumps({"type": "pong"}))

            else:
                await websocket.send_text(json.dumps({
                    "type": "error",
                    "content": f"Unknown message type: '{msg_type}'.",
                }))

    except WebSocketDisconnect:
        await manager.disconnect(room_id, user_id)
    except Exception:
        logger.exception("Unexpected error in WS handler for room %s", room_id)
        await manager.disconnect(room_id, user_id)
