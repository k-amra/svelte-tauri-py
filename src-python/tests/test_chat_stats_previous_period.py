"""Tests for the compare-to-previous-period option in chat_stats.run()."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.scripts import chat_stats
from app.scripts.chat_stats.frame import messages_to_frame
from app.services.harambelogs_models import FullMessage

BASE = datetime(2025, 1, 10, tzinfo=UTC)


def _msg(user_id: str, minutes: int) -> FullMessage:
    return FullMessage(
        type=0,
        text="hello",
        displayName=f"u{user_id}",
        timestamp=BASE + timedelta(minutes=minutes),
        id=f"m{user_id}-{minutes}",
        tags={"room-id": "12345", "user-id": user_id},
        username=f"u{user_id}",
        channel="c",
        raw="hello",
    )


def _params(**overrides):
    defaults = dict(
        channel="c",
        from_date=BASE,
        to_date=BASE + timedelta(days=1),
        compare_previous=True,
    )
    defaults.update(overrides)
    return chat_stats.Params(**defaults)


def test_previous_period_computed_from_the_window_before(monkeypatch) -> None:
    """The previous window is [from - span, from), fetched via a second run_all."""
    calls: list[chat_stats.Params] = []

    async def fake_run_all(params, progress, api=None):
        calls.append(params)
        # Main window has 2 chatters; the previous window has 1.
        if params.from_date == BASE:
            return messages_to_frame([_msg("1", 0), _msg("2", 1)]), False, False, "123", None, [{}], {}, []
        return messages_to_frame([_msg("3", 0)]), False, False, "123", None, [{}], {}, []

    monkeypatch.setattr(chat_stats, "run_all", fake_run_all)
    result = chat_stats.run(_params())

    assert len(calls) == 2
    prev_params = calls[1]
    assert prev_params.from_date == BASE - timedelta(days=1)
    assert prev_params.to_date == BASE
    # The previous-window fetch must not recurse.
    assert prev_params.compare_previous is False

    assert result.previous_period is not None
    assert result.previous_period.total_messages == 1
    assert result.previous_period.unique_chatters == 1
    assert result.previous_period.from_date == (BASE - timedelta(days=1)).isoformat()
    # Length stats flow from compute_overview for the delta tiles.
    assert result.previous_period.median_message_length == 5.0
    assert result.previous_period.max_message_length == 5
    assert result.previous_period.avg_words_per_message == 1.0
    # Vocab stats are not in compute_overview yet — nullable, no delta shown.
    assert result.previous_period.vocab_richness is None


def test_previous_period_empty_window_returns_zeroed_summary(monkeypatch) -> None:
    async def fake_run_all(params, progress, api=None):
        if params.from_date == BASE:
            return messages_to_frame([_msg("1", 0)]), False, False, "123", None, [{}], {}, []
        return messages_to_frame([]), False, False, "123", None, [{}], {}, []

    monkeypatch.setattr(chat_stats, "run_all", fake_run_all)
    result = chat_stats.run(_params())

    assert result.previous_period is not None
    assert result.previous_period.total_messages == 0
    assert result.previous_period.unique_chatters == 0
    assert result.previous_period.peak_concurrent_chatters is None


def test_previous_period_skipped_by_default(monkeypatch) -> None:
    calls: list[chat_stats.Params] = []

    async def fake_run_all(params, progress, api=None):
        calls.append(params)
        return messages_to_frame([_msg("1", 0)]), False, False, "123", None, [{}], {}, []

    monkeypatch.setattr(chat_stats, "run_all", fake_run_all)
    result = chat_stats.run(_params(compare_previous=False))

    assert len(calls) == 1
    assert result.previous_period is None


def test_previous_week_mode_uses_fixed_seven_day_window(monkeypatch) -> None:
    calls: list[chat_stats.Params] = []

    async def fake_run_all(params, progress, api=None):
        calls.append(params)
        if params.from_date == BASE:
            return messages_to_frame([_msg("1", 0)]), False, False, "123", None, [{}], {}, []
        return messages_to_frame([]), False, False, "123", None, [{}], {}, []

    monkeypatch.setattr(chat_stats, "run_all", fake_run_all)
    # 3-day current window; previous_week is still a fixed 7-day window.
    result = chat_stats.run(
        _params(to_date=BASE + timedelta(days=3), comparison_mode="previous_week")
    )

    prev_params = calls[1]
    assert prev_params.from_date == BASE - timedelta(days=7)
    assert prev_params.to_date == BASE
    assert result.previous_period is not None
    assert result.previous_period.mode == "previous_week"


def test_custom_mode_resolves_explicit_window(monkeypatch) -> None:
    calls: list[chat_stats.Params] = []

    async def fake_run_all(params, progress, api=None):
        calls.append(params)
        if params.from_date == BASE:
            return messages_to_frame([_msg("1", 0)]), False, False, "123", None, [{}], {}, []
        return messages_to_frame([]), False, False, "123", None, [{}], {}, []

    monkeypatch.setattr(chat_stats, "run_all", fake_run_all)
    cmp_from = BASE - timedelta(days=14)
    cmp_to = BASE - timedelta(days=7)
    result = chat_stats.run(
        _params(
            comparison_mode="custom",
            compare_from_date=cmp_from,
            compare_to_date=cmp_to,
        )
    )

    prev_params = calls[1]
    assert prev_params.from_date == cmp_from
    assert prev_params.to_date == cmp_to
    assert result.previous_period is not None
    assert result.previous_period.mode == "custom"


def test_custom_mode_requires_both_dates() -> None:
    import pytest

    with pytest.raises(ValueError, match="requires both"):
        _params(comparison_mode="custom", compare_from_date=BASE - timedelta(days=1))

    with pytest.raises(ValueError, match="requires both"):
        _params(comparison_mode="custom", compare_to_date=BASE - timedelta(days=1))


def test_custom_mode_rejects_inverted_range() -> None:
    import pytest

    with pytest.raises(ValueError, match="compare_from_date must be before"):
        _params(
            comparison_mode="custom",
            compare_from_date=BASE,
            compare_to_date=BASE - timedelta(days=1),
        )


def test_previous_year_uses_calendar_year(monkeypatch) -> None:
    from app.scripts.chat_stats import _resolve_comparison_window

    # Same date one year back, including the Feb 29 → Feb 28 fallback.
    normal = datetime(2025, 3, 15, tzinfo=UTC)
    leap_day = datetime(2024, 2, 29, tzinfo=UTC)

    assert _resolve_comparison_window(
        _params(from_date=normal, to_date=normal + timedelta(days=1), comparison_mode="previous_year")
    ) == (datetime(2024, 3, 15, tzinfo=UTC), normal)
    assert _resolve_comparison_window(
        _params(
            from_date=leap_day, to_date=leap_day + timedelta(days=1), comparison_mode="previous_year"
        )
    ) == (datetime(2023, 2, 28, tzinfo=UTC), leap_day)


def test_params_reject_inverted_range_with_compare(monkeypatch) -> None:
    with pytest.raises(ValueError, match="before to_date"):
        _params(from_date=BASE + timedelta(days=1), to_date=BASE)


def test_top_movers_gain_and_loss() -> None:
    from app.scripts.chat_stats import _top_movers

    # Current: u1 8, u2 2, u3 5. Previous: u1 4, u2 6, u3 5.
    current = messages_to_frame(
        [_msg("1", i) for i in range(8)]
        + [_msg("2", i) for i in range(8, 10)]
        + [_msg("3", i) for i in range(10, 15)]
    )
    previous = messages_to_frame(
        [_msg("1", i) for i in range(4)]
        + [_msg("2", i) for i in range(4, 10)]
        + [_msg("3", i) for i in range(10, 15)]
    )
    gainers, losers = _top_movers(current, previous, top_n=5)
    # Gainers: u1 +4. Losers: u2 −4. u3 unchanged → absent.
    assert [(g.username, g.delta) for g in gainers] == [("u1", 4)]
    assert [(d.username, d.delta) for d in losers] == [("u2", -4)]


def test_top_movers_no_baseline_is_empty() -> None:
    from app.scripts.chat_stats import _top_movers

    current = messages_to_frame([_msg("1", 0)])
    empty = messages_to_frame([])
    assert _top_movers(current, empty) == ([], [])
    assert _top_movers(empty, current) == ([], [])


def test_top_movers_capped() -> None:
    from app.scripts.chat_stats import _top_movers

    # 7 users each gaining 1 message → only top_n kept.
    current = messages_to_frame(
        [_msg(str(u), 2 * u) for u in range(7)] + [_msg(str(u), 2 * u + 1) for u in range(7)]
    )
    previous = messages_to_frame([_msg(str(u), 2 * u) for u in range(7)])
    gainers, losers = _top_movers(current, previous, top_n=5)
    assert len(gainers) == 5
    assert losers == []
