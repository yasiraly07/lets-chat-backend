# LetsChat API Documentation

**Version:** 1.0.0  
**Base URL (local):** `http://localhost:8000`  
**WebSocket Base (local):** `ws://localhost:8000`  
**Interactive Docs:** `http://localhost:8000/docs`

---

## Table of Contents

1. [Overview](#overview)
2. [Core Concepts](#core-concepts)
3. [Quick Start Integration Guide](#quick-start-integration-guide)
4. [REST Endpoints](#rest-endpoints)
   - [Health Check](#1-health-check)
   - [Create Room](#2-create-room)
   - [Room Status](#3-room-status)
   - [List Rooms](#4-list-rooms)
5. [WebSocket API](#websocket-api)
   - [Connecting](#connecting)
   - [Client → Server Messages](#client--server-messages)
   - [Server → Client Messages](#server--client-messages)
   - [Connection Close Codes](#connection-close-codes)
6. [Data Schemas](#data-schemas)
7. [Limits & Constraints](#limits--constraints)
8. [Error Handling](#error-handling)
9. [Configuration Reference](#configuration-reference)
10. [Integration Examples](#integration-examples)
    - [JavaScript / Browser](#javascript--browser)
    - [Python](#python)
    - [React Hook](#react-hook)

---

## Overview

LetsChat is an **ID-based** real-time chat API. There is no user authentication. Any client can:

1. Create a chat room and get a shareable **Room ID**.
2. Share that ID with anyone they want to chat with.
3. Connect to the room via WebSocket with a chosen **username**.
4. Exchange messages in real time.

All messages are persisted to a Postgres database (via Supabase) and replayed to new joiners.

---

## Core Concepts

| Concept | Description |
|---------|-------------|
| **Room ID** | A 10-character uppercase alphanumeric string (e.g. `A3F9C12B0E`). Uniquely identifies a chat session. Created via REST, shared out-of-band. |
| **Username** | Chosen by the user at connection time. Must be 1–32 characters. Must be unique within a room (case-insensitive). |
| **User ID** | A UUID hex string assigned internally per WebSocket session. Opaque to other users but present on every outbound message for reliable client-side identification. |
| **Message History** | The last 50 messages (including system events) are sent to every new joiner on connect. Messages are persisted to Postgres indefinitely. |

---

## Quick Start Integration Guide

### Step 1 — Start the server

```bash
cd backend
.venv\Scripts\activate        # Windows
# source .venv/bin/activate   # macOS / Linux
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

### Step 2 — Create a room (one participant)

```http
POST http://localhost:8000/api/rooms/create
```

Response:
```json
{
  "room_id": "A3F9C12B0E",
  "created_at": "2026-02-27T10:00:00.000000+00:00"
}
```

### Step 3 — Share the Room ID

Send `A3F9C12B0E` to anyone you want to chat with (via link, QR code, copy-paste, etc.).

### Step 4 — Check room status (optional)

Before joining, a client may verify the room exists and is not full:

```http
GET http://localhost:8000/api/rooms/A3F9C12B0E/status
```

### Step 5 — Connect via WebSocket

Every participant (including the creator) connects with:

```
ws://localhost:8000/ws/A3F9C12B0E?username=Alice
```

On successful connection the server immediately sends:
- A **`history`** frame (if there are prior messages).
- A **`system`** frame announcing that `Alice joined the chat`.

### Step 6 — Send and receive messages

Send a chat message:
```json
{ "type": "message", "content": "Hello everyone!" }
```

The server broadcasts it to all participants, including the sender.

---

## REST Endpoints

### 1. Health Check

```
GET /health
```

Returns server status. Useful for uptime monitoring.

**Response `200 OK`**
```json
{
  "status": "ok",
  "version": "1.0.0"
}
```

---

### 2. Create Room

```
POST /api/rooms/create
```

Generates a unique Room ID, registers the room in memory and persists it to the database.

**Request body:** none

**Response `201 Created`**
```json
{
  "room_id": "A3F9C12B0E",
  "created_at": "2026-02-27T10:00:00.000000+00:00"
}
```

| Field | Type | Description |
|-------|------|-------------|
| `room_id` | `string` | 10-char uppercase alphanumeric Room ID |
| `created_at` | `string` | ISO 8601 UTC timestamp |

---

### 3. Room Status

```
GET /api/rooms/{room_id}/status
```

Returns live status of a room. Room IDs are case-insensitive (normalised to uppercase internally).

**Path parameters**

| Parameter | Type | Description |
|-----------|------|-------------|
| `room_id` | `string` | The Room ID to query |

**Response `200 OK` — room exists**
```json
{
  "room_id": "A3F9C12B0E",
  "exists": true,
  "user_count": 2,
  "users": ["Alice", "Bob"],
  "created_at": "2026-02-27T10:00:00.000000+00:00"
}
```

**Response `200 OK` — room does not exist (or no active connections)**
```json
{
  "room_id": "DOESNTEXIST",
  "exists": false,
  "user_count": 0,
  "users": [],
  "created_at": null
}
```

| Field | Type | Description |
|-------|------|-------------|
| `room_id` | `string` | Normalised Room ID |
| `exists` | `boolean` | Whether the room has at least one active WebSocket connection |
| `user_count` | `integer` | Number of currently connected users |
| `users` | `string[]` | Usernames of connected users |
| `created_at` | `string \| null` | ISO 8601 creation timestamp, or `null` if not active |

> **Note:** `exists` reflects in-memory state (active connections). A room that was created but whose last user disconnected will return `exists: false`. The room record itself remains in the database.

---

### 4. List Rooms

```
GET /api/rooms/
```

Returns all rooms with at least one active WebSocket connection. Intended for development and debugging.

**Response `200 OK`**
```json
[
  {
    "room_id": "A3F9C12B0E",
    "exists": true,
    "user_count": 1,
    "users": ["Alice"],
    "created_at": "2026-02-27T10:00:00.000000+00:00"
  }
]
```

---

## WebSocket API

### Connecting

```
ws://{host}/ws/{room_id}?username={username}
```

**Query parameters**

| Parameter | Required | Constraints | Description |
|-----------|----------|-------------|-------------|
| `username` | Yes | 1–32 characters | Display name for this session. Case-insensitively unique within the room. |

**Behaviour on connect:**
- If the Room ID does not exist in memory, it is automatically created (and persisted to the database).
- If the room is at capacity or the username is taken, the server accepts the connection, sends an error frame, and closes with the appropriate close code.
- On success, the server sends a `history` frame (if the room has prior messages) followed by a `system` join message broadcast to all participants.

---

### Client → Server Messages

All messages must be valid JSON objects with a `"type"` field.

#### `message` — Send a chat message

```json
{
  "type": "message",
  "content": "Hello everyone!"
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `type` | `"message"` | Yes | — |
| `content` | `string` | Yes | Message text. 1–4000 characters. Whitespace is trimmed. |

The server broadcasts the message to **all** participants, including the sender.

---

#### `typing` — Broadcast a typing indicator

```json
{
  "type": "typing"
}
```

Notifies all **other** participants that this user is currently typing. The event is **not** echoed back to the sender and is **not** persisted.

---

#### `ping` — Heartbeat

```json
{
  "type": "ping"
}
```

The server replies immediately with a `pong` frame. Use this to keep idle connections alive or verify latency.

---

### Server → Client Messages

#### `history` — Message history (on connect)

Sent **once** immediately after a successful connection, only if the room has prior messages.

```json
{
  "type": "history",
  "messages": [
    {
      "type": "system",
      "room_id": "A3F9C12B0E",
      "content": "Alice joined the chat",
      "timestamp": "2026-02-27T10:00:00.000000+00:00",
      "user_count": 1,
      "users": ["Alice"]
    },
    {
      "type": "message",
      "message_id": "abc123-1740650400.0",
      "room_id": "A3F9C12B0E",
      "user_id": "abc123",
      "username": "Alice",
      "content": "Hello!",
      "timestamp": "2026-02-27T10:00:05.000000+00:00"
    }
  ]
}
```

| Field | Type | Description |
|-------|------|-------------|
| `messages` | `object[]` | Up to 50 most recent messages (mix of `message` and `system` types), ordered oldest → newest |

---

#### `message` — Chat message

Broadcast to every participant (including the sender) when a user sends a message.

```json
{
  "type": "message",
  "message_id": "abc123-1740650400.123456",
  "room_id": "A3F9C12B0E",
  "user_id": "abc123def456abc123def456abc123de",
  "username": "Alice",
  "content": "Hello everyone!",
  "timestamp": "2026-02-27T10:00:05.000000+00:00"
}
```

| Field | Type | Description |
|-------|------|-------------|
| `message_id` | `string` | Unique identifier composed of `user_id` + epoch timestamp |
| `room_id` | `string` | Room the message belongs to |
| `user_id` | `string` | Sender's session UUID (32-char hex) |
| `username` | `string` | Sender's display name |
| `content` | `string` | Message text |
| `timestamp` | `string` | ISO 8601 UTC timestamp |

---

#### `system` — Room event

Sent to all participants when a user joins or leaves.

```json
{
  "type": "system",
  "room_id": "A3F9C12B0E",
  "content": "Bob joined the chat",
  "timestamp": "2026-02-27T10:01:00.000000+00:00",
  "user_count": 2,
  "users": ["Alice", "Bob"]
}
```

| Field | Type | Description |
|-------|------|-------------|
| `content` | `string` | Human-readable event text |
| `user_count` | `integer` | Number of users connected **after** the event |
| `users` | `string[]` | Usernames of all currently connected users **after** the event |

---

#### `typing` — Typing indicator

Sent to all **other** participants (not the sender) when a user sends a `typing` message.

```json
{
  "type": "typing",
  "room_id": "A3F9C12B0E",
  "user_id": "abc123def456abc123def456abc123de",
  "username": "Alice"
}
```

---

#### `pong` — Heartbeat reply

```json
{
  "type": "pong"
}
```

---

#### `error` — Request error

Sent only to the offending client. Does **not** close the connection (except during pre-connect validation — see close codes).

```json
{
  "type": "error",
  "content": "Message too long (max 4000 chars)."
}
```

**Possible `content` values**

| Situation | Message |
|-----------|---------|
| Invalid JSON sent | `Invalid JSON payload.` |
| Unknown message type | `Unknown message type: '<type>'.` |
| Message > 4000 chars | `Message too long (max 4000 chars).` |
| Username already taken | `Username '<name>' is already taken in this room. Please choose another.` |
| Room is at capacity | `Room '<id>' is full (<n> users max).` |

---

#### `rate_limited` — Rate limit exceeded

Sent only to the sender when they exceed the message rate limit. The message is dropped.

```json
{
  "type": "rate_limited",
  "content": "You are sending messages too fast. Please slow down."
}
```

---

### Connection Close Codes

| Code | Meaning | Triggered when |
|------|---------|----------------|
| `1000` | Normal closure | Client disconnects gracefully |
| `4001` | Username taken | Chosen username is already in use in the room |
| `4003` | Room full | Room has reached `MAX_USERS_PER_ROOM` |

---

## Data Schemas

### `CreateRoomResponse`
```
{
  room_id:    string   // 10-char uppercase alphanumeric
  created_at: string   // ISO 8601 UTC
}
```

### `RoomStatusResponse`
```
{
  room_id:    string
  exists:     boolean
  user_count: integer
  users:      string[]
  created_at: string | null
}
```

### `ChatMessage` (server → client)
```
{
  type:       "message"
  message_id: string
  room_id:    string
  user_id:    string
  username:   string
  content:    string
  timestamp:  string   // ISO 8601 UTC
}
```

### `SystemMessage` (server → client)
```
{
  type:       "system"
  room_id:    string
  content:    string
  timestamp:  string
  user_count: integer
  users:      string[]
}
```

### `HistoryFrame` (server → client, once on connect)
```
{
  type:     "history"
  messages: Array<ChatMessage | SystemMessage>
}
```

---

## Limits & Constraints

| Limit | Value | Configurable via |
|-------|-------|-----------------|
| Max users per room | 50 | `MAX_USERS_PER_ROOM` |
| Max message length | 4 000 chars | hardcoded in `ws.py` |
| Username length | 1–32 chars | hardcoded query param constraint |
| Rate limit | 10 messages / 5 seconds | `RATE_LIMIT_MESSAGES` / `RATE_LIMIT_WINDOW_SECONDS` |
| History sent on join | last 50 entries | `MESSAGE_HISTORY_LIMIT` |
| In-memory history cap | 500 entries | `MESSAGE_HISTORY_STORE_LIMIT` |

---

## Error Handling

### HTTP errors

All REST endpoints return standard HTTP status codes. FastAPI's default validation error shape is used for malformed requests:

```json
{
  "detail": [
    {
      "loc": ["query", "username"],
      "msg": "field required",
      "type": "value_error.missing"
    }
  ]
}
```

### WebSocket errors

The WebSocket protocol does not use HTTP status codes after the handshake. All errors are delivered as JSON frames with `"type": "error"` or `"type": "rate_limited"`. The connection remains open unless a close code is sent (see [Connection Close Codes](#connection-close-codes)).

**Recommended client pattern:**
```js
ws.onmessage = (event) => {
  const msg = JSON.parse(event.data);
  if (msg.type === "error") {
    // Show non-fatal error to user, stay connected
  } else if (msg.type === "rate_limited") {
    // Back off sending
  }
};

ws.onclose = (event) => {
  if (event.code === 4001) {
    // Username taken — prompt for a new one
  } else if (event.code === 4003) {
    // Room full
  }
};
```

---

## Configuration Reference

All values are read from the `.env` file in the `backend/` directory (or from environment variables).

| Variable | Default | Description |
|----------|---------|-------------|
| `SUPABASE_URL` | — | Supabase project URL |
| `SUPABASE_KEY` | — | Supabase anon/service key |
| `MAX_USERS_PER_ROOM` | `50` | Maximum concurrent users per room |
| `MESSAGE_HISTORY_LIMIT` | `50` | How many messages are replayed to new joiners |
| `MESSAGE_HISTORY_STORE_LIMIT` | `500` | In-memory message buffer cap per room |
| `RATE_LIMIT_MESSAGES` | `10` | Max messages a user can send per window |
| `RATE_LIMIT_WINDOW_SECONDS` | `5` | Sliding window size for rate limiting (seconds) |
| `CORS_ORIGINS` | `["*"]` | JSON array of allowed CORS origins |

---

## Integration Examples

### JavaScript / Browser

```js
// 1. Create a room
const { room_id } = await fetch("http://localhost:8000/api/rooms/create", {
  method: "POST",
}).then(r => r.json());

console.log("Share this ID:", room_id);

// 2. Connect
const ws = new WebSocket(`ws://localhost:8000/ws/${room_id}?username=Alice`);

ws.onopen = () => {
  console.log("Connected!");
};

ws.onmessage = (event) => {
  const msg = JSON.parse(event.data);

  switch (msg.type) {
    case "history":
      console.log("Message history:", msg.messages);
      break;
    case "message":
      console.log(`[${msg.username}]: ${msg.content}`);
      break;
    case "system":
      console.log(`*** ${msg.content} (${msg.user_count} online) ***`);
      break;
    case "typing":
      console.log(`${msg.username} is typing...`);
      break;
    case "error":
      console.error("Server error:", msg.content);
      break;
    case "rate_limited":
      console.warn("Slow down!");
      break;
  }
};

ws.onclose = (event) => {
  if (event.code === 4001) alert("Username taken. Please choose another.");
  if (event.code === 4003) alert("Room is full.");
};

// 3. Send a message
ws.send(JSON.stringify({ type: "message", content: "Hello!" }));

// 4. Send typing indicator (call while user is typing)
ws.send(JSON.stringify({ type: "typing" }));

// 5. Heartbeat
ws.send(JSON.stringify({ type: "ping" }));
```

---

### Python

```python
import asyncio
import json
import httpx
import websockets

BASE = "http://localhost:8000"
WS   = "ws://localhost:8000"

async def main():
    # 1. Create a room
    async with httpx.AsyncClient() as client:
        resp = await client.post(f"{BASE}/api/rooms/create")
        room_id = resp.json()["room_id"]
    print("Room ID:", room_id)

    # 2. Connect
    uri = f"{WS}/ws/{room_id}?username=PyUser"
    async with websockets.connect(uri) as ws:
        # Receive initial messages (history + join event)
        for _ in range(2):
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=2)
                msg = json.loads(raw)
                print(f"[{msg['type']}]", msg.get("content", ""))
            except asyncio.TimeoutError:
                break

        # Send a message
        await ws.send(json.dumps({"type": "message", "content": "Hi from Python!"}))
        reply = json.loads(await ws.recv())
        print(f"Broadcast received: {reply['content']}")

asyncio.run(main())
```

---

### React Hook

```tsx
import { useEffect, useRef, useState, useCallback } from "react";

type ChatMessage = {
  type: string;
  message_id?: string;
  room_id?: string;
  user_id?: string;
  username?: string;
  content?: string;
  timestamp?: string;
  user_count?: number;
  users?: string[];
  messages?: ChatMessage[];
};

export function useChat(roomId: string, username: string) {
  const ws = useRef<WebSocket | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [status, setStatus] = useState<"connecting" | "connected" | "closed">("connecting");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!roomId || !username) return;

    const socket = new WebSocket(
      `ws://localhost:8000/ws/${roomId}?username=${encodeURIComponent(username)}`
    );
    ws.current = socket;
    setStatus("connecting");

    socket.onopen = () => setStatus("connected");

    socket.onmessage = (event) => {
      const msg: ChatMessage = JSON.parse(event.data);
      if (msg.type === "history") {
        setMessages(msg.messages ?? []);
      } else if (msg.type === "error") {
        setError(msg.content ?? "Unknown error");
      } else {
        setMessages((prev) => [...prev, msg]);
      }
    };

    socket.onclose = (e) => {
      setStatus("closed");
      if (e.code === 4001) setError("Username already taken.");
      if (e.code === 4003) setError("Room is full.");
    };

    return () => socket.close();
  }, [roomId, username]);

  const sendMessage = useCallback((content: string) => {
    ws.current?.send(JSON.stringify({ type: "message", content }));
  }, []);

  const sendTyping = useCallback(() => {
    ws.current?.send(JSON.stringify({ type: "typing" }));
  }, []);

  return { messages, status, error, sendMessage, sendTyping };
}
```

**Usage:**
```tsx
function ChatRoom({ roomId, username }: { roomId: string; username: string }) {
  const { messages, status, error, sendMessage, sendTyping } = useChat(roomId, username);

  return (
    <div>
      <p>Status: {status}</p>
      {error && <p style={{ color: "red" }}>{error}</p>}
      {messages.map((m, i) =>
        m.type === "message" ? (
          <p key={i}><strong>{m.username}:</strong> {m.content}</p>
        ) : m.type === "system" ? (
          <p key={i} style={{ color: "gray" }}>{m.content}</p>
        ) : null
      )}
      <input
        onKeyDown={(e) => { if (e.key === "Enter") sendMessage(e.currentTarget.value); }}
        onChange={sendTyping}
      />
    </div>
  );
}
```
