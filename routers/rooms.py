import uuid
from fastapi import APIRouter

from models import CreateRoomResponse, RoomStatusResponse
from connection_manager import manager
import database as db

router = APIRouter(prefix="/rooms", tags=["rooms"])


@router.post("/create", response_model=CreateRoomResponse, status_code=201)
async def create_room():
    """
    Generate a new unique room ID and register the room.
    Returns the room_id and creation timestamp.
    """
    room_id = uuid.uuid4().hex[:10].upper()
    while manager.room_exists(room_id):
        room_id = uuid.uuid4().hex[:10].upper()

    room = manager.create_room(room_id)
    await db.persist_room(room_id, room.created_at, room.max_users)
    return CreateRoomResponse(room_id=room.room_id, created_at=room.created_at)


@router.get("/{room_id}/status", response_model=RoomStatusResponse)
async def room_status(room_id: str):
    """
    Returns whether the room exists, who is connected, and the creation time.
    Useful before a user tries to join.
    """
    room = manager.get_room(room_id.upper())
    if room is None:
        return RoomStatusResponse(
            room_id=room_id.upper(),
            exists=False,
            user_count=0,
            users=[],
        )
    return RoomStatusResponse(
        room_id=room.room_id,
        exists=True,
        user_count=room.user_count,
        users=room.usernames,
        created_at=room.created_at,
    )


@router.get("/", response_model=list[RoomStatusResponse])
async def list_rooms():
    """
    List all active rooms. Handy for development/debugging.
    """
    return [
        RoomStatusResponse(
            room_id=r.room_id,
            exists=True,
            user_count=r.user_count,
            users=r.usernames,
            created_at=r.created_at,
        )
        for r in manager.rooms.values()
    ]
