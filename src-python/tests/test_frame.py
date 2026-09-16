"""Tests for the frame helpers (pure polars, no network)."""

import polars as pl

from app.scripts.chat_stats.frame import dedupe_by_id


def test_dedupe_by_id_preserves_null_id_row_positions() -> None:
    # Null-id rows used to be relocated after every non-null row by the
    # concat in dedupe_by_id, silently breaking frame order downstream
    # (multi-channel merges sort by ts, then dedupe).
    df = pl.DataFrame({
        "id": ["a", None, "b", "a", None],
        "ts": [1, 2, 3, 4, 5],
        "text": ["1", "2", "3", "4", "5"],
    })
    out = dedupe_by_id(df)
    # keep="last": the first "a" is dropped; null rows keep their positions.
    assert out["text"].to_list() == ["2", "3", "4", "5"]
