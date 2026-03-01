#!/usr/bin/env python3
"""
Database cleaning script for LetsChat.

Removes stale rooms, old messages, and system-message noise from Supabase
while preserving recent / active data.  Supports dry-run mode so you can
preview exactly what would be deleted before pulling the trigger.

Usage
-----
  # Preview what would be deleted (no changes)
  python clean_db.py

  # Actually delete
  python clean_db.py --execute

  # Custom retention windows
  python clean_db.py --execute --msg-days 60 --sys-days 14 --room-days 30

  # Purge ALL data (use with caution)
  python clean_db.py --execute --purge-all

Environment
-----------
Reads SUPABASE_URL / SUPABASE_KEY from the same .env that the backend uses
(via config.Settings).
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from datetime import datetime, timedelta, timezone

from supabase import AsyncClient, acreate_client

from config import settings

# ── Logging ────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("clean_db")

# ── Helpers ────────────────────────────────────────────────────────────────

async def _get_client() -> AsyncClient:
    return await acreate_client(settings.supabase_url, settings.supabase_key)


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def _cutoff(days: int) -> datetime:
    return datetime.now(timezone.utc) - timedelta(days=days)


# ── Counting helpers (Supabase JS-style; returns int) ──────────────────────

async def _count_old_messages(db: AsyncClient, cutoff: str) -> int:
    """Count chat messages older than *cutoff*."""
    res = (
        await db.table("messages")
        .select("id", count="exact")
        .eq("type", "message")
        .lt("timestamp", cutoff)
        .execute()
    )
    return res.count or 0


async def _count_old_system_messages(db: AsyncClient, cutoff: str) -> int:
    """Count system messages (join / leave) older than *cutoff*."""
    res = (
        await db.table("messages")
        .select("id", count="exact")
        .eq("type", "system")
        .lt("timestamp", cutoff)
        .execute()
    )
    return res.count or 0


async def _count_orphan_rooms(db: AsyncClient, cutoff: str) -> int:
    """
    Count rooms that are older than *cutoff* AND have zero messages
    remaining in the messages table.
    """
    # Fetch candidate room IDs (created before cutoff)
    rooms_res = (
        await db.table("rooms")
        .select("room_id")
        .lt("created_at", cutoff)
        .execute()
    )
    if not rooms_res.data:
        return 0

    orphan_count = 0
    for row in rooms_res.data:
        rid = row["room_id"]
        msg = (
            await db.table("messages")
            .select("id", count="exact")
            .eq("room_id", rid)
            .limit(1)
            .execute()
        )
        if (msg.count or 0) == 0:
            orphan_count += 1
    return orphan_count


# ── Deletion helpers ───────────────────────────────────────────────────────

async def _delete_old_messages(db: AsyncClient, cutoff: str) -> int:
    res = (
        await db.table("messages")
        .delete()
        .eq("type", "message")
        .lt("timestamp", cutoff)
        .execute()
    )
    return len(res.data) if res.data else 0


async def _delete_old_system_messages(db: AsyncClient, cutoff: str) -> int:
    res = (
        await db.table("messages")
        .delete()
        .eq("type", "system")
        .lt("timestamp", cutoff)
        .execute()
    )
    return len(res.data) if res.data else 0


async def _delete_orphan_rooms(db: AsyncClient, cutoff: str) -> int:
    rooms_res = (
        await db.table("rooms")
        .select("room_id")
        .lt("created_at", cutoff)
        .execute()
    )
    if not rooms_res.data:
        return 0

    deleted = 0
    for row in rooms_res.data:
        rid = row["room_id"]
        msg = (
            await db.table("messages")
            .select("id", count="exact")
            .eq("room_id", rid)
            .limit(1)
            .execute()
        )
        if (msg.count or 0) == 0:
            await db.table("rooms").delete().eq("room_id", rid).execute()
            deleted += 1
    return deleted


async def _purge_all(db: AsyncClient) -> tuple[int, int]:
    """Nuclear option — delete every row in messages and rooms."""
    msg = await db.table("messages").delete().neq("id", "00000000-0000-0000-0000-000000000000").execute()
    rm  = await db.table("rooms").delete().neq("room_id", "").execute()
    return (len(msg.data) if msg.data else 0, len(rm.data) if rm.data else 0)


# ── Main routine ───────────────────────────────────────────────────────────

async def run(args: argparse.Namespace):
    db = await _get_client()

    try:
        # ── Stats before cleanup ──────────────────────────────────────
        total_msgs = (await db.table("messages").select("id", count="exact").execute()).count or 0
        total_rooms = (await db.table("rooms").select("room_id", count="exact").execute()).count or 0
        log.info("Current DB size: %d messages, %d rooms", total_msgs, total_rooms)

        if args.purge_all:
            if not args.execute:
                log.warning("[DRY RUN] --purge-all would delete ALL %d messages and %d rooms", total_msgs, total_rooms)
            else:
                log.warning("Purging ALL data …")
                msgs, rooms = await _purge_all(db)
                log.info("Purged %d messages and %d rooms", msgs, rooms)
            return

        msg_cutoff  = _iso(_cutoff(args.msg_days))
        sys_cutoff  = _iso(_cutoff(args.sys_days))
        room_cutoff = _iso(_cutoff(args.room_days))

        log.info(
            "Retention policy:  chat messages > %d days  |  system messages > %d days  |  empty rooms > %d days",
            args.msg_days, args.sys_days, args.room_days,
        )
        log.info("Cut-off timestamps:  msgs=%s  sys=%s  rooms=%s", msg_cutoff, sys_cutoff, room_cutoff)

        # ── Count what will be affected ───────────────────────────────
        n_msgs    = await _count_old_messages(db, msg_cutoff)
        n_sys     = await _count_old_system_messages(db, sys_cutoff)
        n_orphans = await _count_orphan_rooms(db, room_cutoff)

        log.info("Found:  %d old chat messages  |  %d old system messages  |  %d orphan rooms", n_msgs, n_sys, n_orphans)

        if n_msgs + n_sys + n_orphans == 0:
            log.info("Nothing to clean. Database is tidy!")
            return

        if not args.execute:
            log.warning("[DRY RUN] No changes made. Re-run with --execute to apply deletions.")
            return

        # ── Delete ────────────────────────────────────────────────────
        d_msgs    = await _delete_old_messages(db, msg_cutoff)
        d_sys     = await _delete_old_system_messages(db, sys_cutoff)
        d_orphans = await _delete_orphan_rooms(db, room_cutoff)

        log.info("Deleted:  %d chat messages  |  %d system messages  |  %d orphan rooms", d_msgs, d_sys, d_orphans)

        # ── Stats after cleanup ───────────────────────────────────────
        remaining_msgs = (await db.table("messages").select("id", count="exact").execute()).count or 0
        remaining_rooms = (await db.table("rooms").select("room_id", count="exact").execute()).count or 0
        log.info("After cleanup: %d messages, %d rooms", remaining_msgs, remaining_rooms)

    finally:
        try:
            await db.aclose()
        except AttributeError:
            pass  # older client versions lack aclose()


# ── CLI ────────────────────────────────────────────────────────────────────

def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Clean old / junk data from the LetsChat Supabase database.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument(
        "--execute",
        action="store_true",
        help="Actually perform deletions. Without this flag the script only previews (dry run).",
    )
    p.add_argument(
        "--msg-days",
        type=int,
        default=30,
        metavar="N",
        help="Delete chat messages older than N days (default: 30).",
    )
    p.add_argument(
        "--sys-days",
        type=int,
        default=7,
        metavar="N",
        help="Delete system (join/leave) messages older than N days (default: 7).",
    )
    p.add_argument(
        "--room-days",
        type=int,
        default=14,
        metavar="N",
        help="Delete empty rooms older than N days (default: 14).",
    )
    p.add_argument(
        "--purge-all",
        action="store_true",
        help="Delete ALL messages and rooms. Ignores retention flags.",
    )
    return p.parse_args(argv)


def main():
    args = parse_args()
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
