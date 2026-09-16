"""Fetches channel emotes from 7TV, BTTV, and FFZ.

Requires the Twitch User ID (from the `room-id` IRC tag) for 7TV and BTTV.
FFZ can fallback to the channel name. Results are cached for 24h under
the app data dir to avoid rate limits and speed up repeated runs.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path

import httpx

from app.core import paths

log = logging.getLogger(__name__)

CACHE_TTL_S = 24 * 60 * 60  # 24 hours


def _cache_path(channel_name: str, user_id: str | None) -> Path:
    name = f"{user_id or channel_name.lower()}.json"
    return paths.cache_root() / "emotes" / name


def _load_cache(channel_name: str, user_id: str | None) -> dict[str, str] | None:
    p = _cache_path(channel_name, user_id)
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        # Corrupt or unreadable cache — treat as a miss. A permission error
        # would otherwise be invisible and every fetch would re-download.
        log.warning("emote cache read failed for %s: %s — treating as miss", p, e)
        return None
    if not isinstance(data, dict):
        return None
    try:
        ts = float(data.get("ts", 0))
    except (TypeError, ValueError):
        return None
    if time.time() - ts >= CACHE_TTL_S:
        return None
    cached = data.get("emotes")
    return cached if isinstance(cached, dict) else None


def _save_cache(channel_name: str, user_id: str | None, emotes: dict[str, str]) -> None:
    p = _cache_path(channel_name, user_id)
    p.parent.mkdir(parents=True, exist_ok=True)
    try:
        p.write_text(json.dumps({"ts": time.time(), "emotes": emotes}), encoding="utf-8")
    except OSError as e:
        log.warning("emote cache write failed: %s", e)


async def _fetch_7tv(client: httpx.AsyncClient, user_id: str) -> dict[str, str]:
    try:
        r = await client.get(f"https://7tv.io/v3/users/twitch/{user_id}")
        if r.status_code == 200:
            data = r.json()
            emote_set = data.get("emote_set", {})
            return {e["id"]: e["name"] for e in emote_set.get("emotes", []) if "id" in e and "name" in e}
    except Exception as e:
        log.debug("7tv fetch failed: %s", e)
    return {}


async def _fetch_bttv(client: httpx.AsyncClient, user_id: str) -> dict[str, str]:
    try:
        r = await client.get(f"https://api.betterttv.net/3/cached/users/twitch/{user_id}")
        if r.status_code == 200:
            data = r.json()
            emotes = {}
            for e in data.get("channelEmotes", []) + data.get("sharedEmotes", []):
                if "id" in e and "code" in e:
                    emotes[e["id"]] = e["code"]
            return emotes
    except Exception as e:
        log.debug("bttv fetch failed: %s", e)
    return {}


async def _fetch_ffz(client: httpx.AsyncClient, channel_name: str, user_id: str | None) -> dict[str, str]:
    try:
        url = (
            f"https://api.frankerfacez.com/v1/room/id/{user_id}"
            if user_id
            else f"https://api.frankerfacez.com/v1/room/{channel_name}"
        )
        r = await client.get(url)
        if r.status_code == 200:
            data = r.json()
            emotes = {}
            for set_data in data.get("sets", {}).values():
                for e in set_data.get("emoticons", []):
                    if "id" in e and "name" in e:
                        emotes[str(e["id"])] = e["name"]
            return emotes
    except Exception as e:
        log.debug("ffz fetch failed: %s", e)
    return {}


async def fetch_channel_emotes(channel_name: str, twitch_user_id: str | None) -> dict[str, str]:
    """Return a mapping of emote_id -> emote_name for the channel."""
    cached = _load_cache(channel_name, twitch_user_id)
    if cached is not None:
        return cached

    async with httpx.AsyncClient(timeout=10.0, headers={"User-Agent": "TauriSidecar/1.0 (EmoteFetcher)"}) as client:
        tasks = []
        if twitch_user_id:
            tasks.append(_fetch_7tv(client, twitch_user_id))
            tasks.append(_fetch_bttv(client, twitch_user_id))
        tasks.append(_fetch_ffz(client, channel_name, twitch_user_id))

        results = await asyncio.gather(*tasks, return_exceptions=True)

    emotes: dict[str, str] = {}
    for res in results:
        if isinstance(res, dict):
            emotes.update(res)

    if emotes:
        _save_cache(channel_name, twitch_user_id, emotes)

    return emotes
