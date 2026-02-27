"""
Comprehensive integration tests for the LetsChat backend.
Run with: python test_backend.py
"""
import asyncio
import json
import sys
import time
import httpx
import websockets

BASE_HTTP = "http://localhost:8000"
BASE_WS   = "ws://localhost:8000"

PASS = "\033[92m  PASS\033[0m"
FAIL = "\033[91m  FAIL\033[0m"
HEAD = "\033[94m{}\033[0m"

results: list[tuple[str, bool, str]] = []


def record(name: str, passed: bool, detail: str = ""):
    results.append((name, passed, detail))
    icon = PASS if passed else FAIL
    print(f"{icon}  {name}" + (f" — {detail}" if detail else ""))


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

def get(path: str) -> httpx.Response:
    return httpx.get(f"{BASE_HTTP}{path}", timeout=10)

def post(path: str, **kwargs) -> httpx.Response:
    return httpx.post(f"{BASE_HTTP}{path}", timeout=10, **kwargs)


# ---------------------------------------------------------------------------
# Test: Health
# ---------------------------------------------------------------------------

def test_health():
    r = get("/health")
    record("Health check returns 200", r.status_code == 200)
    body = r.json()
    record("Health body has status=ok", body.get("status") == "ok")


# ---------------------------------------------------------------------------
# Test: Room creation
# ---------------------------------------------------------------------------

def test_create_room() -> str:
    r = post("/api/rooms/create")
    record("POST /api/rooms/create → 201", r.status_code == 201)
    body = r.json()
    record("Response has room_id", "room_id" in body)
    record("Response has created_at", "created_at" in body)
    room_id = body.get("room_id", "")
    record("room_id is 10 chars uppercase", len(room_id) == 10 and room_id.isupper())
    return room_id


# ---------------------------------------------------------------------------
# Test: Room status
# ---------------------------------------------------------------------------

def test_room_status(room_id: str):
    r = get(f"/api/rooms/{room_id}/status")
    record("GET /api/rooms/{id}/status → 200", r.status_code == 200)
    body = r.json()
    record("Status: exists=true", body.get("exists") is True)
    record("Status: user_count=0 (no one joined yet)", body.get("user_count") == 0)

    # Non-existent room
    r2 = get("/api/rooms/DOESNOTEXIST/status")
    record("Non-existent room: exists=false", r2.json().get("exists") is False)


# ---------------------------------------------------------------------------
# Test: List rooms
# ---------------------------------------------------------------------------

def test_list_rooms(room_id: str):
    r = get("/api/rooms/")
    record("GET /api/rooms/ → 200", r.status_code == 200)
    ids = [rm["room_id"] for rm in r.json()]
    record("Created room appears in list", room_id in ids)


# ---------------------------------------------------------------------------
# Test: WebSocket — basic chat flow
# ---------------------------------------------------------------------------

async def test_ws_basic(room_id: str):
    uri_alice = f"{BASE_WS}/ws/{room_id}?username=Alice"
    uri_bob   = f"{BASE_WS}/ws/{room_id}?username=Bob"

    async with websockets.connect(uri_alice) as alice:
        # Alice should NOT receive history (empty room)
        # Alice should receive her own join system message
        msg = json.loads(await asyncio.wait_for(alice.recv(), timeout=5))
        record("WS: Alice gets system join message", msg["type"] == "system", msg.get("content", ""))
        record("WS: System message has user_count=1", msg.get("user_count") == 1)

        async with websockets.connect(uri_bob) as bob:
            # Alice should receive Bob's join event
            alice_recv = json.loads(await asyncio.wait_for(alice.recv(), timeout=5))
            record("WS: Alice notified of Bob joining", alice_recv.get("type") == "system" and "Bob" in alice_recv.get("content", ""))
            record("WS: Room now has 2 users", alice_recv.get("user_count") == 2)

            # Bob receives own join (and history which has Alice's join system msg)
            bob_msgs = []
            for _ in range(2):   # history + join system msg
                try:
                    m = json.loads(await asyncio.wait_for(bob.recv(), timeout=3))
                    bob_msgs.append(m)
                except asyncio.TimeoutError:
                    break
            types = [m["type"] for m in bob_msgs]
            record("WS: Bob receives history or system on join", "history" in types or "system" in types)

            # Alice sends a chat message
            await alice.send(json.dumps({"type": "message", "content": "Hello Bob!"}))

            # Bob should receive it
            chat = json.loads(await asyncio.wait_for(bob.recv(), timeout=5))
            record("WS: Bob receives Alice's message", chat.get("type") == "message")
            record("WS: Message content correct", chat.get("content") == "Hello Bob!")
            record("WS: Message has username=Alice", chat.get("username") == "Alice")
            record("WS: Message has message_id", bool(chat.get("message_id")))
            record("WS: Message has timestamp", bool(chat.get("timestamp")))

            # Alice also receives her own broadcast
            own = json.loads(await asyncio.wait_for(alice.recv(), timeout=5))
            record("WS: Sender also receives own message", own.get("content") == "Hello Bob!")

            # Ping/pong
            await alice.send(json.dumps({"type": "ping"}))
            pong = json.loads(await asyncio.wait_for(alice.recv(), timeout=5))
            record("WS: ping → pong", pong.get("type") == "pong")

        # Bob disconnected — Alice should receive leave notification
        leave = json.loads(await asyncio.wait_for(alice.recv(), timeout=5))
        record("WS: Alice notified of Bob leaving", leave.get("type") == "system" and "left" in leave.get("content", ""))
        record("WS: user_count back to 1 after Bob leaves", leave.get("user_count") == 1)


# ---------------------------------------------------------------------------
# Test: WebSocket — typing indicator
# ---------------------------------------------------------------------------

async def test_ws_typing(room_id: str):
    uri_alice = f"{BASE_WS}/ws/{room_id}?username=TypistA"
    uri_bob   = f"{BASE_WS}/ws/{room_id}?username=TypistB"

    async with websockets.connect(uri_alice) as alice:
        await alice.recv()  # join system msg

        async with websockets.connect(uri_bob) as bob:
            await alice.recv()  # Bob joined
            # Drain Bob's join messages
            for _ in range(2):
                try:
                    await asyncio.wait_for(bob.recv(), timeout=1)
                except asyncio.TimeoutError:
                    break

            # Alice sends typing
            await alice.send(json.dumps({"type": "typing"}))

            # Bob receives typing event
            t = json.loads(await asyncio.wait_for(bob.recv(), timeout=5))
            record("WS: Typing indicator received by peer", t.get("type") == "typing")
            record("WS: Typing has correct username", t.get("username") == "TypistA")

            # Alice should NOT receive her own typing event — check with timeout
            try:
                echo = json.loads(await asyncio.wait_for(alice.recv(), timeout=1.5))
                record("WS: Typing NOT echoed to sender", echo.get("type") != "typing", f"got {echo}")
            except asyncio.TimeoutError:
                record("WS: Typing NOT echoed to sender", True)


# ---------------------------------------------------------------------------
# Test: WebSocket — duplicate username rejection
# ---------------------------------------------------------------------------

async def test_ws_duplicate_username(room_id: str):
    uri = f"{BASE_WS}/ws/{room_id}?username=Dupeuser"
    async with websockets.connect(uri) as first:
        await first.recv()  # join msg

        try:
            async with websockets.connect(uri) as second:
                msg = json.loads(await asyncio.wait_for(second.recv(), timeout=5))
                record("WS: Duplicate username → error message", msg.get("type") == "error")
                record("WS: Error mentions username", "Dupeuser" in msg.get("content", ""))
                # Connection should be closed by server
                try:
                    await asyncio.wait_for(second.recv(), timeout=2)
                    record("WS: Server closed connection after username error", False)
                except (websockets.exceptions.ConnectionClosed, asyncio.TimeoutError):
                    record("WS: Server closed connection after username error", True)
        except websockets.exceptions.ConnectionClosed:
            record("WS: Duplicate username → connection rejected", True)


# ---------------------------------------------------------------------------
# Test: WebSocket — rate limiting
# ---------------------------------------------------------------------------

async def test_ws_rate_limit(room_id: str):
    uri = f"{BASE_WS}/ws/{room_id}?username=Spammer"
    async with websockets.connect(uri) as ws:
        await ws.recv()  # join msg

        rate_limited = False
        for i in range(15):  # exceed the 10/5s limit
            await ws.send(json.dumps({"type": "message", "content": f"spam {i}"}))

        # Collect all responses to find rate_limited
        deadline = time.time() + 5
        while time.time() < deadline:
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=1)
                m = json.loads(raw)
                if m.get("type") == "rate_limited":
                    rate_limited = True
                    break
            except asyncio.TimeoutError:
                break

        record("WS: Rate limiting kicks in after burst", rate_limited)


# ---------------------------------------------------------------------------
# Test: WebSocket — message history on reconnect
# ---------------------------------------------------------------------------

async def test_ws_history(room_id: str):
    # Send a message in the room first
    uri = f"{BASE_WS}/ws/{room_id}?username=HistoryUser"
    async with websockets.connect(uri) as ws:
        await ws.recv()  # join
        await ws.send(json.dumps({"type": "message", "content": "Remember me!"}))
        await ws.recv()  # own broadcast

    # Reconnect with a different username — should receive history
    await asyncio.sleep(0.5)
    uri2 = f"{BASE_WS}/ws/{room_id}?username=NewGuy"
    async with websockets.connect(uri2) as ws2:
        msgs = []
        for _ in range(3):
            try:
                m = json.loads(await asyncio.wait_for(ws2.recv(), timeout=3))
                msgs.append(m)
            except asyncio.TimeoutError:
                break

        types = [m["type"] for m in msgs]
        history_msg = next((m for m in msgs if m.get("type") == "history"), None)
        record("WS: New joiner receives history frame", history_msg is not None)
        if history_msg:
            contents = [m.get("content", "") for m in history_msg.get("messages", [])]
            record("WS: History contains previously sent message", "Remember me!" in contents)


# ---------------------------------------------------------------------------
# Test: Invalid JSON / unknown type
# ---------------------------------------------------------------------------

async def test_ws_errors(room_id: str):
    uri = f"{BASE_WS}/ws/{room_id}?username=ErrorBot"
    async with websockets.connect(uri) as ws:
        await ws.recv()  # join

        # Invalid JSON
        await ws.send("not json at all")
        err = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
        record("WS: Invalid JSON → error type", err.get("type") == "error")

        # Unknown message type
        await ws.send(json.dumps({"type": "explode"}))
        err2 = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
        record("WS: Unknown message type → error", err2.get("type") == "error")

        # Overly long message
        await ws.send(json.dumps({"type": "message", "content": "x" * 4001}))
        err3 = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
        record("WS: Oversized message → error", err3.get("type") == "error")


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

async def run_async(room_id: str):
    await test_ws_basic(room_id)

    r2 = post("/api/rooms/create").json()["room_id"]
    await test_ws_typing(r2)

    r3 = post("/api/rooms/create").json()["room_id"]
    await test_ws_duplicate_username(r3)

    r4 = post("/api/rooms/create").json()["room_id"]
    await test_ws_rate_limit(r4)

    r5 = post("/api/rooms/create").json()["room_id"]
    await test_ws_history(r5)

    r6 = post("/api/rooms/create").json()["room_id"]
    await test_ws_errors(r6)


def main():
    print(HEAD.format("\n========== LetsChat Backend Tests ==========\n"))

    # HTTP tests
    print(HEAD.format("--- HTTP / REST ---"))
    test_health()
    room_id = test_create_room()
    test_room_status(room_id)
    test_list_rooms(room_id)

    # WebSocket tests
    print(HEAD.format("\n--- WebSocket ---"))
    asyncio.run(run_async(room_id))

    # Summary
    passed = sum(1 for _, ok, _ in results if ok)
    failed = sum(1 for _, ok, _ in results if not ok)
    total  = len(results)
    print(HEAD.format(f"\n========== Results: {passed}/{total} passed =========="))
    if failed:
        print("\033[91mFailed tests:\033[0m")
        for name, ok, detail in results:
            if not ok:
                print(f"  ✗ {name}" + (f" — {detail}" if detail else ""))
        sys.exit(1)
    else:
        print("\033[92mAll tests passed!\033[0m")


if __name__ == "__main__":
    main()
