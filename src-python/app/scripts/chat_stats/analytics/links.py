"""URL / domain / platform analytics."""
from __future__ import annotations

import polars as pl

from ..constants import URL_RE


def compute_links(df: pl.DataFrame, top_n: int) -> dict:
    links_df = df.filter(pl.col("text").str.contains(URL_RE))
    messages_with_links = links_df.height
    if messages_with_links == 0:
        return {
            "messages_with_links": 0,
            "top_domains": [],
            "platform_links": {
                "twitch_clips": 0,
                "youtube": 0,
                "discord": 0,
                "x_twitter": 0,
                "kick": 0,
                "other": 0,
            },
        }

    # Extract URLs once; classify each URL individually so platform counts
    # and top_domains are consistent (link-level, not message-level).
    urls = (
        links_df.select(pl.col("text").str.extract_all(URL_RE).alias("url"))
        .explode("url", empty_as_null=True)
        .drop_nulls("url")
    )

    domains = (
        urls.select(
            pl.col("url").str.to_lowercase().str.extract(r"^(?:https?://)?(?:www\.)?([^/]+)", 1).alias("domain")
        )
        .drop_nulls("domain")
        .group_by("domain")
        .len()
        .sort(["len", "domain"], descending=[True, False])
        .head(top_n)
    )

    u_lower = urls["url"].str.to_lowercase()
    is_clip = u_lower.str.contains(r"clips\.twitch\.tv|twitch\.tv/\w+/clip/")
    is_yt = u_lower.str.contains(r"youtube\.com|youtu\.be")
    is_dc = u_lower.str.contains(r"discord\.(gg|com)")
    is_x = u_lower.str.contains(r"x\.com|twitter\.com")
    is_kick = u_lower.str.contains(r"kick\.com")
    any_platform = is_clip | is_yt | is_dc | is_x | is_kick

    return {
        "messages_with_links": messages_with_links,
        "top_domains": [{"domain": d, "count": c} for d, c in zip(domains["domain"], domains["len"], strict=True)],
        "platform_links": {
            "twitch_clips": int(is_clip.sum()),
            "youtube": int(is_yt.sum()),
            "discord": int(is_dc.sum()),
            "x_twitter": int(is_x.sum()),
            "kick": int(is_kick.sum()),
            "other": int((~any_platform).sum()),
        },
    }
