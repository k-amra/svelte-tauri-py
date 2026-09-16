"""Unit tests for multi-interval cache coverage (pure helpers, no disk)."""

from datetime import UTC, datetime

from app.services.log_cache import coverage_intervals, covers, merge_coverage


def _d(day: int) -> datetime:
    return datetime(2024, 1, day, tzinfo=UTC)


def test_disjoint_intervals_do_not_merge():
    cov = merge_coverage([(_d(1), _d(5))], (_d(20), _d(25)))
    assert cov == [(_d(1), _d(5)), (_d(20), _d(25))]
    assert not covers(cov, _d(6), _d(19))
    assert covers(cov, _d(2), _d(4))
    assert covers(cov, _d(21), _d(24))


def test_touching_intervals_merge():
    cov = merge_coverage([(_d(1), _d(5))], (_d(5), _d(10)))
    assert cov == [(_d(1), _d(10))]


def test_legacy_single_interval_still_reads():
    meta = {"covered_from": _d(1).isoformat(), "covered_to": _d(5).isoformat()}
    assert coverage_intervals(meta) == [(_d(1), _d(5))]
