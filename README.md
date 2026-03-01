# LetsChat — Backend

FastAPI + WebSocket real-time chat backend with Supabase (Postgres) persistence, per-user rate limiting, and input validation.

## Features

- **Room-based chat** — create a room, share the ID, anyone can join
- **WebSocket messaging** — real-time broadcast to all participants
- **Supabase / Postgres** — rooms and messages persisted across restarts
- **Rate limiting** — sliding-window throttle per user (default: 10 msgs / 5 s)
- **Input validation** — regex-checked usernames & room IDs, content length caps
- **Graceful disconnect handling** — guards against double-disconnect races
- **DB cleaning utility** — `clean_db.py` script with dry-run mode

## Quick Start

```bash
cd backend

# 1. Create & activate a virtual environment
python -m venv .venv
.venv\Scripts\activate        # Windows
# source .venv/bin/activate   # macOS / Linux

# 2. Install dependencies
pip install -r requirements.txt

# 3. Configure environment (required)
# Ensure .env contains SUPABASE_URL and SUPABASE_KEY

# 4. Run the development server
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

For production (single process + safer WS settings behind proxies):

```bash
uvicorn main:app --host 0.0.0.0 --port $PORT --workers 1 --loop asyncio --http h11 --ws websockets --ws-per-message-deflate false --proxy-headers
```

Interactive API docs → **http://localhost:8000/docs**

## Configuration

All settings are loaded via `config.py` (pydantic-settings) and can be overridden with a `.env` file or environment variables.

| Variable | Default | Description |
|----------|---------|-------------|
| `SUPABASE_URL` | **Required** | Supabase project URL |
| `SUPABASE_KEY` | **Required** | Supabase anon key |
| `MAX_USERS_PER_ROOM` | `50` | Max concurrent users per room |
| `MESSAGE_HISTORY_LIMIT` | `50` | Messages sent to new joiners |
| `MESSAGE_HISTORY_STORE_LIMIT` | `500` | In-memory message cap before trimming |
| `RATE_LIMIT_MESSAGES` | `10` | Max messages per window |
| `RATE_LIMIT_WINDOW_SECONDS` | `5` | Sliding window duration (seconds) |
| `CORS_ORIGINS` | `["*"]` (dev default) | Allowed frontend origins; set explicit URLs in production |

### Required `.env` example

```dotenv
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_KEY=your-supabase-anon-key

# Dev
CORS_ORIGINS=["http://localhost:5173"]

# Production example
# CORS_ORIGINS=["https://yourapp.com"]
```

## API Reference

### REST Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/rooms/create` | Create a new room → returns `room_id` |
| `GET` | `/api/rooms/{room_id}/status` | Room info: exists, users, created_at |
| `GET` | `/api/rooms/` | List all active rooms (debug) |
| `GET` | `/health` | Health check |

### WebSocket

```
ws://localhost:8000/ws/{ROOM_ID}?username=YourName
```

**Client → Server**

| Type | Payload | Purpose |
|------|---------|---------|
| `message` | `{ "type": "message", "content": "Hello!" }` | Send a chat message |
| `ping` | `{ "type": "ping" }` | Keep-alive |

**Server → Client**

| Type | When | Key Fields |
|------|------|------------|
| `history` | On connect | `messages[]` (last 50) |
| `system` | User joined / left | `content`, `user_count`, `users[]` |
| `message` | Chat message | `username`, `content`, `timestamp`, `user_id`, `message_id` |
| `pong` | Reply to ping | — |
| `error` | Bad request / rate limit | `content` |

## Chat Flow

1. **Create** — `POST /api/rooms/create` → `{ "room_id": "A3F9C12B0E" }`
2. **Share** — send the room ID to participants
3. **Connect** — each user opens `ws://host/ws/A3F9C12B0E?username=Alice`
4. **Chat** — messages are broadcast to everyone in real time
5. **Cleanup** — when the last user disconnects, the in-memory room is removed

## Database Cleaning

A standalone script removes stale data while preserving recent activity.

```bash
# Preview what would be deleted (dry run — no changes)
python clean_db.py

# Actually delete with default retention
python clean_db.py --execute

# Custom retention windows
python clean_db.py --execute --msg-days 60 --sys-days 14 --room-days 30

# Purge everything
python clean_db.py --execute --purge-all
```

**Default retention:** chat messages 30 days, system messages 7 days, empty rooms 14 days.

## Project Structure

```
backend/
├── main.py                 # FastAPI app, CORS, lifespan, router registration
├── config.py               # pydantic-settings configuration
├── connection_manager.py   # In-memory room/user state, WebSocket broadcast
├── database.py             # Async Supabase client — persist rooms & messages
├── models.py               # Pydantic request / response schemas
├── clean_db.py             # Database cleaning utility (CLI)
├── test_backend.py         # Test suite
├── requirements.txt        # Python dependencies
├── API_DOCUMENTATION.md    # Extended API docs
└── routers/
    ├── rooms.py            # REST endpoints for room management
    └── ws.py               # WebSocket endpoint & message handling
```
