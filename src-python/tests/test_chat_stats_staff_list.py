"""Tests for the optional staff and subscriber lists in chat_stats."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.scripts.chat_stats import Params, compute_stats
from app.scripts.chat_stats.analytics.health import (
    compute_staff_list,
    compute_subscriber_list,
)
from app.scripts.chat_stats.frame import messages_to_frame
from app.services.harambelogs_models import FullMessage

BASE = datetime(2025, 1, 1, tzinfo=UTC)


def _msg(user_id: str, username: str, role: str, minutes: int) -> FullMessage:
    badges = {
        "broadcaster": "broadcaster/1",
        "moderator": "moderator/1",
        "vip": "vip/1",
        "subscriber": "subscriber/1",
    }.get(role)
    tags: dict = {"room-id": "12345", "user-id": user_id}
    if badges:
        tags["badges"] = badges
    return FullMessage(
        type=0,
        text="hi",
        displayName=username,
        timestamp=BASE + timedelta(minutes=minutes),
        id=f"m{minutes}",
        tags=tags,
        username=username,
        channel="c",
        raw="hi",
    )


def _params(**overrides) -> Params:
    defaults = dict(
        channel="c",
        from_date=BASE,
        to_date=datetime(2025, 1, 2, tzinfo=UTC),
    )
    defaults.update(overrides)
    return Params(**defaults)


def test_staff_list_includes_mods_vips_and_broadcaster() -> None:
    df = messages_to_frame(
        [
            _msg("1", "boss", "broadcaster", 0),
            _msg("2", "mod1", "moderator", 1),
            _msg("2", "mod1", "moderator", 2),
            _msg("3", "vip1", "vip", 3),
        ]
    )
    out = compute_staff_list(df)["staff_list"]
    assert [m["username"] for m in out] == ["boss", "mod1", "vip1"]
    assert out[0]["role"] == "broadcaster"
    assert out[1]["messageCount"] == 2
    assert out[1]["firstSeen"] == (BASE + timedelta(minutes=1)).isoformat()
    assert out[1]["lastSeen"] == (BASE + timedelta(minutes=2)).isoformat()


def test_staff_list_excludes_regulars_and_subscribers() -> None:
    df = messages_to_frame(
        [
            _msg("1", "chatter", "regular", 0),
            _msg("2", "sub", "subscriber", 1),
        ]
    )
    assert compute_staff_list(df)["staff_list"] == []


def test_staff_list_includes_users_demoted_to_regular() -> None:
    # Anyone seen holding a staff badge in the range is listed, even if their
    # final state is regular. The role shown is their last staff role.
    df = messages_to_frame(
        [
            _msg("1", "promoted", "regular", 0),
            _msg("1", "promoted", "moderator", 1),
            _msg("2", "demoted", "moderator", 2),
            _msg("2", "demoted", "regular", 3),
        ]
    )
    out = compute_staff_list(df)["staff_list"]
    # Equal role and count: tie broken by user_id ("1" < "2").
    assert [(m["username"], m["role"]) for m in out] == [
        ("promoted", "moderator"),
        ("demoted", "moderator"),
    ]
    # messageCount covers all messages in the range, not just staff-badged ones.
    assert all(m["messageCount"] == 2 for m in out)


def test_staff_list_uses_last_staff_role() -> None:
    # Role changed between two staff roles: the most recent one wins.
    df = messages_to_frame(
        [
            _msg("1", "promoted", "moderator", 0),
            _msg("1", "promoted", "vip", 1),
        ]
    )
    out = compute_staff_list(df)["staff_list"]
    assert [(m["username"], m["role"]) for m in out] == [("promoted", "vip")]


def test_staff_list_sorted_by_role_then_volume() -> None:
    df = messages_to_frame(
        [
            _msg("1", "quietmod", "moderator", 0),
            _msg("2", "loudmod", "moderator", 1),
            _msg("2", "loudmod", "moderator", 2),
            _msg("2", "loudmod", "moderator", 3),
            _msg("3", "vip", "vip", 4),
        ]
    )
    out = compute_staff_list(df)["staff_list"]
    assert [(m["username"], m["messageCount"]) for m in out] == [
        ("loudmod", 3),
        ("quietmod", 1),
        ("vip", 1),
    ]


def test_staff_list_empty_frame() -> None:
    assert compute_staff_list(messages_to_frame([]))["staff_list"] == []


def test_compute_stats_includes_staff_list_only_when_opted_in() -> None:
    df = messages_to_frame([_msg("1", "mod", "moderator", 0)])

    out = compute_stats(df, _params(), {})
    # Opt-out: the key is absent from the raw dict; Result defaults it to [].
    assert "staff_list" not in out

    out = compute_stats(df, _params(include_staff_list=True), {})
    assert [m["username"] for m in out["staff_list"]] == ["mod"]
    assert out["staff_list"][0]["role"] == "moderator"


def test_subscriber_list() -> None:
    df = messages_to_frame(
        [
            _msg("1", "sub1", "subscriber", 0),
            _msg("1", "sub1", "subscriber", 1),
            _msg("2", "sub2", "subscriber", 2),
            _msg("3", "mod", "moderator", 3),
        ]
    )
    out = compute_subscriber_list(df)
    assert out["subscriber_count"] == 2
    assert [(m["username"], m["messageCount"]) for m in out["subscriber_list"]] == [
        ("sub1", 2),
        ("sub2", 1),
    ]
    # Mods/VIPs never leak into the subscriber roster.
    assert all(m["role"] == "subscriber" for m in out["subscriber_list"])


def test_subscriber_list_capped_but_count_is_true() -> None:
    df = messages_to_frame([_msg(str(i), f"sub{i}", "subscriber", i) for i in range(5)])
    out = compute_subscriber_list(df, top_n=3)
    assert out["subscriber_count"] == 5
    assert len(out["subscriber_list"]) == 3


def test_compute_stats_includes_subscriber_list_only_when_opted_in() -> None:
    df = messages_to_frame([_msg("1", "sub", "subscriber", 0)])

    out = compute_stats(df, _params(), {})
    assert "subscriber_list" not in out

    out = compute_stats(df, _params(include_subscriber_list=True), {})
    assert out["subscriber_count"] == 1
    assert [m["username"] for m in out["subscriber_list"]] == ["sub"]
