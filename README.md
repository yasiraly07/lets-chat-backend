# LetsChat — Backend

FastAPI-powered WebSocket chat backend with ID-based room sessions.

## Quick Start

```bash
cd backend

# 1. Create a virtual environment
python -m venv .venv
.venv\Scripts\activate        # Windows
# source .venv/bin/activate   # macOS / Linux

# 2. Install dependencies
pip install -r requirements.txt

# 3. Run the development server
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

Interactive API docs → http://localhost:8000/docs

---

## API Reference

### REST

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/rooms/create` | Create a new room, returns `room_id` |
| `GET` | `/api/rooms/{room_id}/status` | Check if a room exists and who is in it |
| `GET` | `/api/rooms/` | List all active rooms (debug) |
| `GET` | `/health` | Health check |

### WebSocket

```
ws://localhost:8000/ws/{ROOM_ID}?username=YourName
```

**Client → Server messages**

```json
{ "type": "message", "content": "Hello everyone!" }
{ "type": "ping" }
```

**Server → Client message types**

| Type | When | Key fields |
|------|------|------------|
| `history` | On connect | `messages[]` (last 50) |
| `system` | User joined/left | `content`, `user_count`, `users[]` |
| `message` | Chat message | `username`, `content`, `timestamp`, `user_id` |
| `pong` | Reply to ping | — |
| `error` | Bad request | `content` |

---

## Flow

1. **Creator** calls `POST /api/rooms/create` → receives `room_id` (e.g. `A3F9C12B0E`)
2. Creator shares the `room_id` with anyone they want to chat with
3. Each participant picks a **username** and connects:
   ```
   ws://localhost:8000/ws/A3F9C12B0E?username=Alice
   ```
4. Messages sent by any participant are broadcast to everyone in the room in real time
5. When all users disconnect, the room is automatically cleaned up

---

## Project Structure

```
backend/
├── main.py               # FastAPI app, CORS, router registration
├── connection_manager.py # WebSocket state: rooms, users, broadcast
├── models.py             # Pydantic request/response schemas
├── requirements.txt
└── routers/
    ├── rooms.py          # REST endpoints for room management
    └── ws.py             # WebSocket endpoint
```
