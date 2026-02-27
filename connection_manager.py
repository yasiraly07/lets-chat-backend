import json
import logging
from collections import deque
from datetime import datetime, timezone
from typing import Dict
from fastapi import WebSocket

from config import settings
import database as db

logger = logging.getLogger(__name__)


class ConnectedUser:
    def __init__(self, websocket: WebSocket, username: str, user_id: str):
        self.websocket = websocket
        self.username = username
        self.user_id = user_id
        self.joined_at = datetime.now(timezone.utc).isoformat()
        # Rate-limiting: sliding window over recent message timestamps
        self._msg_timestamps: deque[float] = deque()

    def is_rate_limited(self) -> bool:
        """
        Returns True when the user exceeds settings.rate_limit_messages
        in the last settings.rate_limit_window_seconds.
        """
        now = datetime.now(timezone.utc).timestamp()
        window = settings.rate_limit_window_seconds
        while self._msg_timestamps and self._msg_timestamps[0] < now - window:
            self._msg_timestamps.popleft()
        if len(self._msg_timestamps) >= settings.rate_limit_messages:
            return True
        self._msg_timestamps.append(now)
        return False


class Room:
    def __init__(self, room_id: str, max_users: int | None = None):
        self.room_id = room_id
        self.created_at = datetime.now(timezone.utc).isoformat()
        self.max_users: int = max_users or settings.max_users_per_room
        # user_id -> ConnectedUser
        self.users: Dict[str, ConnectedUser] = {}
        self.message_history: list[dict] = []
        self._history_loaded = False

    @property
    def user_count(self) -> int:
        return len(self.users)

    @property
    def is_full(self) -> bool:
        return self.user_count >= self.max_users

    @property
    def usernames(self) -> list[str]:
        return [u.username for u in self.users.values()]

    def add_user(self, user: ConnectedUser):
        self.users[user.user_id] = user

    def remove_user(self, user_id: str) -> ConnectedUser | None:
        return self.users.pop(user_id, None)

    def get_user(self, user_id: str) -> ConnectedUser | None:
        return self.users.get(user_id)

    def username_taken(self, username: str) -> bool:
        return any(u.username.lower() == username.lower() for u in self.users.values())


class ConnectionManager:
    def __init__(self):
        # room_id -> Room
        self.rooms: Dict[str, Room] = {}

    # ------------------------------------------------------------------ rooms

    def room_exists(self, room_id: str) -> bool:
        return room_id in self.rooms

    def get_room(self, room_id: str) -> Room | None:
        return self.rooms.get(room_id)

    def create_room(self, room_id: str, max_users: int | None = None) -> Room:
        room = Room(room_id, max_users=max_users)
        self.rooms[room_id] = room
        return room

    def delete_room_if_empty(self, room_id: str):
        room = self.rooms.get(room_id)
        if room and room.user_count == 0:
            del self.rooms[room_id]
            logger.info("Room %s deleted (empty)", room_id)

    # --------------------------------------------------------------- connect

    async def connect(self, websocket: WebSocket, room_id: str, user_id: str, username: str):
        await websocket.accept()

        room = self.rooms.get(room_id)
        if room is None:
            room = self.create_room(room_id)

        user = ConnectedUser(websocket=websocket, username=username, user_id=user_id)
        room.add_user(user)
        logger.info("User '%s' (%s) joined room %s (%d/%d)",
                    username, user_id, room_id, room.user_count, room.max_users)

        # Load history from DB on first live connection, then cache in-memory
        if not room._history_loaded:
            history = await db.load_recent_messages(room_id, limit=settings.message_history_limit)
            room.message_history = history
            room._history_loaded = True

        if room.message_history:
            await self._send_personal(websocket, {
                "type": "history",
                "messages": room.message_history,
            })

        # Notify everyone that user joined
        join_msg = self._build_system_message(
            f"{username} joined the chat",
            room_id=room_id,
            user_count=room.user_count,
            users=room.usernames,
        )
        room.message_history.append(join_msg)
        await db.persist_message(join_msg)
        await self.broadcast(room_id, join_msg)

    # ------------------------------------------------------------ disconnect

    async def disconnect(self, room_id: str, user_id: str):
        room = self.rooms.get(room_id)
        if room is None:
            return

        user = room.remove_user(user_id)
        if user is None:
            return

        logger.info("User '%s' (%s) left room %s", user.username, user_id, room_id)

        leave_msg = self._build_system_message(
            f"{user.username} left the chat",
            room_id=room_id,
            user_count=room.user_count,
            users=room.usernames,
        )
        room.message_history.append(leave_msg)
        await db.persist_message(leave_msg)
        await self.broadcast(room_id, leave_msg)

        self.delete_room_if_empty(room_id)

    # -------------------------------------------------------------- broadcast

    async def broadcast(self, room_id: str, payload: dict):
        room = self.rooms.get(room_id)
        if room is None:
            return

        # Snapshot to avoid mutation during iteration
        snapshot = list(room.users.items())
        dead_users: list[str] = []

        for uid, user in snapshot:
            try:
                await user.websocket.send_text(json.dumps(payload))
            except Exception:
                logger.warning("Dead socket for '%s' in room %s", user.username, room_id)
                dead_users.append(uid)

        for uid in dead_users:
            await self.disconnect(room_id, uid)

    async def send_chat_message(self, room_id: str, user_id: str, content: str) -> bool:
        """
        Broadcast a chat message. Returns False when the sender is rate-limited.
        """
        room = self.rooms.get(room_id)
        if room is None:
            return True

        user = room.get_user(user_id)
        if user is None:
            return True

        if user.is_rate_limited():
            logger.info("Rate-limited user '%s' in room %s", user.username, room_id)
            return False

        msg = {
            "type": "message",
            "message_id": f"{user_id}-{datetime.now(timezone.utc).timestamp()}",
            "room_id": room_id,
            "user_id": user_id,
            "username": user.username,
            "content": content,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        room.message_history.append(msg)
        if len(room.message_history) > settings.message_history_store_limit:
            room.message_history = room.message_history[-settings.message_history_store_limit:]

        await db.persist_message(msg)
        await self.broadcast(room_id, msg)
        return True

    # -------------------------------------------------------- typing indicator

    async def broadcast_typing(self, room_id: str, user_id: str):
        """Relay a typing event to everyone else in the room (not persisted)."""
        room = self.rooms.get(room_id)
        if room is None:
            return
        user = room.get_user(user_id)
        if user is None:
            return

        payload = {
            "type": "typing",
            "room_id": room_id,
            "user_id": user_id,
            "username": user.username,
        }
        snapshot = list(room.users.items())
        for uid, u in snapshot:
            if uid == user_id:
                continue
            try:
                await u.websocket.send_text(json.dumps(payload))
            except Exception:
                logger.warning("Dead socket while sending typing to '%s'", u.username)

    # ----------------------------------------------------------- send personal

    async def _send_personal(self, websocket: WebSocket, payload: dict):
        try:
            await websocket.send_text(json.dumps(payload))
        except Exception:
            logger.exception("Failed to send personal message")

    # ------------------------------------------------------------- helpers

    @staticmethod
    def _build_system_message(text: str, room_id: str, user_count: int, users: list[str]) -> dict:
        return {
            "type": "system",
            "room_id": room_id,
            "content": text,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "user_count": user_count,
            "users": users,
        }


# Singleton shared across the app
manager = ConnectionManager()
