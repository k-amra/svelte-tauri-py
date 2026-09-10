"""Tests for emote fetching, tag parsing, and the Top Emotes integration."""

import asyncio
from datetime import UTC, datetime

import polars as pl
import pytest

from app.core import paths
from app.scripts import chat_stats
from app.services import emotes
from app.services.harambelogs_models import FullMessage


@pytest.fixture(autouse=True)
def _data_dir(tmp_path):
    paths.init(str(tmp_path))


def tagged_msg(username: str, text: str, emotes_tag: str | None) -> FullMessage:
    tags: dict = {"room-id": "12345"}
    if emotes_tag is not None:
        tags["emotes"] = emotes_tag
    return FullMessage(
        type=0,
        text=text,
        displayName=username,
        timestamp=datetime(2024, 1, 15, 10, 0, tzinfo=UTC),
        id="1",
        tags=tags,
        username=username,
        channel="chan",
        raw=text,
    )


def _count(df: pl.DataFrame, emote_map: dict[str, str], limit: int = 50) -> list[dict]:
    twitch_emotes = chat_stats._parse_twitch_emotes(df)
    counts, _ = chat_stats._count_emotes(df, twitch_emotes, emote_map, limit)
    return counts


def test_count_parses_irc_tag_occurrences():
    df = chat_stats.messages_to_frame(
        [
            tagged_msg("a", "Kappa hello Kappa", "25:0-4,12-16"),
            tagged_msg("b", "Keepo Keepo Keepo", "1902:0-4,6-10,12-16"),
            tagged_msg("c", "plain text", None),
        ]
    )
    counts = _count(df, {"25": "Kappa", "1902": "Keepo"})
    assert counts == [
        {"name": "Keepo", "count": 3},
        {"name": "Kappa", "count": 2},
    ]


def test_count_unresolvable_positions_kept_in_brackets():
    # Empty text and malformed ranges can't yield a name: keep the raw id.
    df = chat_stats.messages_to_frame(
        [
            tagged_msg("a", "", "999:0-2"),
            tagged_msg("b", "hello", "999:xx"),
        ]
    )
    assert _count(df, {}) == [{"name": "[999]", "count": 2}]


def test_count_mixes_tag_extraction_and_third_party_text_match():
    # "Kappa" comes from the Twitch tag; "KEKW" (third-party, never tagged)
    # is matched against the catalog — without double-counting "Kappa".
    df = chat_stats.messages_to_frame([tagged_msg("a", "Kappa KEKW Kappa", "25:0-4,11-15")])
    counts = _count(df, {"25": "Kappa", "b1": "KEKW"})
    assert counts == [
        {"name": "Kappa", "count": 2},
        {"name": "KEKW", "count": 1},
    ]


def test_count_falls_back_to_text_matching_without_tags():
    df = chat_stats.messages_to_frame([tagged_msg("a", "hello Kappa world", None)])
    assert _count(df, {"25": "Kappa"}) == [{"name": "Kappa", "count": 1}]


def test_count_is_case_sensitive():
    df = chat_stats.messages_to_frame([tagged_msg("a", "LULW lulw LULW", None)])
    assert _count(df, {"x": "LULW"}) == [{"name": "LULW", "count": 2}]


def test_count_keeps_underscored_names_whole():
    df = chat_stats.messages_to_frame([tagged_msg("a", "monkaS_Steer hello monkaS_Steer", None)])
    assert _count(df, {"m": "monkaS_Steer"}) == [
        {"name": "monkaS_Steer", "count": 2}
    ]


def test_count_missing_column_returns_empty():
    df = pl.DataFrame({"username": ["a"], "text": ["hi"]})
    assert _count(df, {"25": "Kappa"}) == []


def test_empty_stats_includes_top_emotes():
    params = chat_stats.Params(
        channel="chan",
        from_date=datetime(2024, 1, 1, tzinfo=UTC),
        to_date=datetime(2024, 1, 2, tzinfo=UTC),
    )
    assert chat_stats.compute_stats(chat_stats.messages_to_frame([]), params, {})["top_emotes"] == []


class FakeResponse:
    def __init__(self, payload: dict, status: int = 200):
        self._payload = payload
        self.status_code = status

    def json(self) -> dict:
        return self._payload


def make_fake_client(routes: dict, calls: list):
    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def get(self, url: str):
            calls.append(url)
            for prefix, resp in routes.items():
                if url.startswith(prefix):
                    return resp
            return FakeResponse({}, status=404)

    return FakeClient


def test_fetch_merges_all_three_providers(monkeypatch):
    calls: list = []
    routes = {
        "https://7tv.io": FakeResponse({"emote_set": {"emotes": [{"id": "7a", "name": "RAGEY"}]}}),
        "https://api.betterttv.net": FakeResponse(
            {"channelEmotes": [{"id": "b1", "code": "KEKW"}], "sharedEmotes": []}
        ),
        "https://api.frankerfacez.com": FakeResponse(
            {"sets": {"1": {"emoticons": [{"id": 99, "name": "ZULUL"}]}}}
        ),
    }
    monkeypatch.setattr(emotes.httpx, "AsyncClient", lambda **kw: make_fake_client(routes, calls)())
    result = asyncio.run(emotes.fetch_channel_emotes("chan", "12345"))
    assert result == {"7a": "RAGEY", "b1": "KEKW", "99": "ZULUL"}
    assert len(calls) == 3


def test_fetch_without_user_id_uses_ffz_only(monkeypatch):
    calls: list = []
    routes = {"https://api.frankerfacez.com/v1/room/chan": FakeResponse({"sets": {}})}
    monkeypatch.setattr(emotes.httpx, "AsyncClient", lambda **kw: make_fake_client(routes, calls)())
    assert asyncio.run(emotes.fetch_channel_emotes("chan", None)) == {}
    assert calls == ["https://api.frankerfacez.com/v1/room/chan"]


def test_fetch_uses_24h_disk_cache(monkeypatch):
    calls: list = []
    routes = {
        "https://api.frankerfacez.com": FakeResponse({"sets": {"1": {"emoticons": [{"id": 99, "name": "ZULUL"}]}}})
    }
    monkeypatch.setattr(emotes.httpx, "AsyncClient", lambda **kw: make_fake_client(routes, calls)())
    assert asyncio.run(emotes.fetch_channel_emotes("chan", "12345")) == {"99": "ZULUL"}
    assert len(calls) == 3  # 7tv + bttv 404, ffz hit
    # Second call: served from disk, no HTTP at all.
    calls.clear()

    def _no_http(**kw):
        raise AssertionError("no HTTP expected")

    monkeypatch.setattr(emotes.httpx, "AsyncClient", _no_http)
    assert asyncio.run(emotes.fetch_channel_emotes("chan", "12345")) == {"99": "ZULUL"}
    assert calls == []


def test_run_rejects_inverted_range():
    with pytest.raises(ValueError, match="before to_date"):
        chat_stats.run(
            chat_stats.Params(
                channel="chan",
                from_date=datetime(2024, 1, 2, tzinfo=UTC),
                to_date=datetime(2024, 1, 1, tzinfo=UTC),
            )
        )


def test_run_includes_top_emotes_and_twitch_id(monkeypatch):
    async def fake_fetch(params, progress):
        return [tagged_msg("a", "Kappa Kappa", "25:0-4,6-10")], False

    async def fake_emotes(channel_name, user_id):
        assert channel_name == "chan"
        assert user_id == "12345"  # extracted from the room-id tag
        return {"25": "Kappa"}

    monkeypatch.setattr(chat_stats, "_fetch_all", fake_fetch)
    monkeypatch.setattr(chat_stats, "fetch_channel_emotes", fake_emotes)
    result = chat_stats.run(
        chat_stats.Params(
            channel="chan",
            from_date=datetime(2024, 1, 1, tzinfo=UTC),
            to_date=datetime(2024, 1, 2, tzinfo=UTC),
        )
    )
    assert result.top_emotes == [chat_stats.EmoteCount(name="Kappa", count=2)]
    assert result.from_cache is False
    # Native emote names must not leak into the vocabulary stats.
    assert all(w.word != "kappa" for w in result.top_words)
