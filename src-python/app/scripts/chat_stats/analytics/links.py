"""URL / domain / platform analytics."""
from __future__ import annotations

import polars as pl

from ..constants import URL_RE, URL_TRAILING_PUNCT_RE

# Cap on the "all URLs" list returned to the UI dialog. A year-long range
# on a busy channel can have tens of thousands of unique URLs; sending all
# of them would bloat the job payload. 5000 fits the dialog comfortably and
# stays well under 1 MB even with long query strings.
MAX_ALL_URLS = 5000


def _normalize_url_expr() -> pl.Expr:
    """Trailing-punct strip + trailing-slash strip + scheme/host lowercase.

    Applied before grouping so near-duplicates collapse into one row. Only
    the scheme and host are lowercased (case-insensitive per RFC 3986) — the
    path, query and fragment keep their case because provider IDs are often
    case-sensitive (e.g. YouTube `?v=kJQP7kiw5Fk` ≠ `?v=kjqp7kiw5fk`;
    lowercasing the whole URL would corrupt such links).
    """
    cleaned = (
        pl.col("url")
        .str.replace_all(URL_TRAILING_PUNCT_RE, "")
        .str.replace(r"/+$", "")  # str.replace = regex in Polars
    )
    scheme_host = cleaned.str.extract(r"^(https?://[^/]+)", 1).str.to_lowercase()
    rest = cleaned.str.replace(r"^https?://[^/]+", "")
    # Rows without a scheme match (shouldn't happen — URL_RE requires one)
    # fall back to the cleaned value instead of nulling out.
    return (scheme_host + rest).fill_null(cleaned)


def compute_links(
    df: pl.DataFrame, top_n: int, all_urls_limit: int = MAX_ALL_URLS
) -> dict:
    links_df = df.filter(pl.col("text").str.contains(URL_RE))
    messages_with_links = links_df.height
    if messages_with_links == 0:
        return {
            "messages_with_links": 0,
            "top_domains": [],
            "top_urls": [],
            "all_urls": [],
            "unique_url_count": 0,
            "platform_links": {
                "twitch_clips": 0, "youtube": 0, "discord": 0,
                "x_twitter": 0, "kick": 0, "other": 0,
            },
        }

    urls = (
        links_df.select(pl.col("text").str.extract_all(URL_RE).alias("url"))
        .explode("url", empty_as_null=True)
        .drop_nulls("url")
        .with_columns(_normalize_url_expr().alias("url"))
        # Defensive: a message of "https://" alone normalizes to empty.
        .filter(pl.col("url").str.len_chars() > 0)
    )

    domains = (
        urls.select(
            pl.col("url").str.extract(r"^(?:https?://)?(?:www\.)?([^/]+)", 1).alias("domain")
        )
        .drop_nulls("domain")
        .group_by("domain")
        .len()
        .sort(["len", "domain"], descending=[True, False])
        .head(top_n)
    )

    # Exact URL counts. Counts *occurrences*, not distinct messages — one
    # message pasting the same URL twice contributes 2. That matches how a
    # user reads "how many times was this pasted". (`urls` is already
    # normalized, so near-duplicates share one bucket.)
    top_urls = (
        urls.group_by("url")
        .len()
        .sort(["len", "url"], descending=[True, False])
        .head(top_n)
    )

    # The full ranked list for the "show all" dialog. Much higher cap than
    # top_n so the dialog shows everything the user asked for, but still
    # bounded to keep the IPC payload sane.
    all_urls = (
        urls.group_by("url")
        .len()
        .sort(["len", "url"], descending=[True, False])
        .head(all_urls_limit)
    )

    # True unique count (used by the UI header so a hit cap is visible).
    unique_url_count = int(urls.select(pl.col("url").n_unique()).item())

    # Lowercasing here is detection-only (platform substrings are matched
    # case-insensitively); the stored URLs above keep their original case.
    url_lc = urls["url"].str.to_lowercase()
    is_clip = url_lc.str.contains(r"clips\.twitch\.tv|twitch\.tv/\w+/clip/")
    is_yt = url_lc.str.contains(r"youtube\.com|youtu\.be")
    is_dc = url_lc.str.contains(r"discord\.(gg|com)")
    is_x = url_lc.str.contains(r"x\.com|twitter\.com")
    is_kick = url_lc.str.contains(r"kick\.com")
    any_platform = is_clip | is_yt | is_dc | is_x | is_kick

    return {
        "messages_with_links": messages_with_links,
        "top_domains": [
            {"domain": d, "count": c}
            for d, c in zip(domains["domain"], domains["len"], strict=True)
        ],
        "top_urls": [
            {"url": u, "count": c}
            for u, c in zip(top_urls["url"], top_urls["len"], strict=True)
        ],
        "all_urls": [
            {"url": u, "count": c}
            for u, c in zip(all_urls["url"], all_urls["len"], strict=True)
        ],
        "unique_url_count": unique_url_count,
        "platform_links": {
            "twitch_clips": int(is_clip.sum()),
            "youtube": int(is_yt.sum()),
            "discord": int(is_dc.sum()),
            "x_twitter": int(is_x.sum()),
            "kick": int(is_kick.sum()),
            "other": int((~any_platform).sum()),
        },
    }
