from pydantic import BaseModel
from typing import Optional
from datetime import datetime


class CreateRoomRequest(BaseModel):
    username: str


class JoinRoomRequest(BaseModel):
    username: str


class MessagePayload(BaseModel):
    type: str          # "message" | "system" | "ping"
    content: Optional[str] = None
    username: Optional[str] = None
    room_id: Optional[str] = None
    timestamp: Optional[str] = None
    user_count: Optional[int] = None


class RoomInfo(BaseModel):
    room_id: str
    created_at: str
    user_count: int
    users: list[str]


class CreateRoomResponse(BaseModel):
    room_id: str
    created_at: str


class RoomStatusResponse(BaseModel):
    room_id: str
    exists: bool
    user_count: int
    users: list[str]
    created_at: Optional[str] = None
