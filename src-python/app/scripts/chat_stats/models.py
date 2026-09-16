"""Pydantic models for chat_stats Params / Result and every nested shape.

Field order is load-bearing for the JSON schema — do not reorder.
"""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator

ComparisonMode = Literal[
    "previous_period",
    "previous_week",
    "previous_month",
    "previous_year",
    "custom",
]


class Params(BaseModel):
    # Deprecated: use `channels`. Kept for backwards compat; the validator
    # coerces it into `channels` and keeps it in sync for single-channel runs.
    channel: str | None = None
    channel_id_type: Literal["channel", "channelid"] = "channel"
    # New: one or more channels (multi-channel runs pool their messages).
    channels: list[str] = Field(default_factory=list)

    # Optional single-user filter. When set, the assembled frame is filtered
    # to this user before any analytics run. None = whole-channel behavior.
    # `user` matches against the IRC login (`username`), `userid` against the
    # numeric Twitch id (`user_id`); mirrors upstream's /user vs /userid split.
    user: str | None = None
    user_id_type: Literal["user", "userid"] = "user"

    from_date: datetime
    # NOTE: to_date is EXCLUSIVE — see fetcher._slice_range / fetcher._get_months_range.
    to_date: datetime

    top_n: int = Field(20, ge=5, le=100)
    top_words_n: int = Field(50, ge=10, le=200)
    top_emotes_n: int = Field(50, ge=10, le=200)
    top_phrases_n: int = Field(20, ge=0, le=50)

    include_commands: bool = True
    include_links: bool = True
    include_mentions: bool = True
    include_duplicates: bool = True
    include_phrases: bool = False
    include_sessions: bool = True
    include_concentration: bool = True
    include_message_class: bool = True

    include_new_returning: bool = True
    include_emote_pairs: bool = True
    include_engagement: bool = True
    include_anomalies: bool = True
    # Latent: not exposed in the UI (the toggle was removed because the
    # optional `langdetect` dep isn't shipped). Enable by adding the dep
    # and re-adding the toggles to ChatStatsPanel.svelte — do NOT remove
    # the backend logic thinking it's dead code.
    include_language: bool = False
    include_copy_paste_chains: bool = True

    # Tier 2 toggles — default off.
    include_mention_graph: bool = False
    include_mutual_mentions: bool = False
    include_emote_centrality: bool = False
    include_emote_entropy: bool = False
    include_lorenz: bool = False
    include_bot_scores: bool = False
    include_length_trend: bool = False
    include_cohort_retention: bool = False
    include_language_by_day: bool = False
    include_quote_replies: bool = False
    include_staff_list: bool = False
    include_subscriber_list: bool = False
    compare_previous: bool = False
    comparison_mode: ComparisonMode = "previous_period"
    compare_from_date: datetime | None = None
    compare_to_date: datetime | None = None

    session_gap_minutes: int = Field(15, ge=2, le=120)
    anomaly_sigma: float = Field(3.0, ge=1.0, le=6.0)
    force_refresh: bool = False

    # Hard ceiling on the requested range. Beyond this the per-day arrays
    # (messages_per_day, daily_new_chatters, daily_returning_chatters) each
    # hold one entry per calendar day and would bloat the job result
    # payload. 366 * 3 ≈ 1100 entries worst case. Raise explicitly if the
    # payload size is acceptable.
    max_range_days: int = Field(366, ge=1, le=3660)

    @model_validator(mode="after")
    def _validate_channels(self) -> Params:
        # Coerce `channel` -> `channels` for backwards compat.
        if not self.channels and self.channel:
            self.channels = [self.channel]
        if not self.channels:
            raise ValueError("at least one channel is required")
        # Dedupe case-insensitively (Twitch logins are case-insensitive),
        # strip whitespace, keep the first-seen casing.
        seen: dict[str, str] = {}
        for raw in self.channels:
            name = raw.strip()
            if not name:
                continue
            key = name.lower()
            if key not in seen:
                seen[key] = name
        deduped = list(seen.values())
        if not deduped:
            raise ValueError("at least one non-empty channel is required")
        if len(deduped) > 3:
            raise ValueError(f"at most 3 channels are supported; got {len(deduped)}")
        self.channels = deduped
        # Keep `channel` in sync for legacy readers (emote cache keys, etc.).
        self.channel = deduped[0] if len(deduped) == 1 else None
        return self

    @model_validator(mode="after")
    def _validate_date_order(self) -> Params:
        if self.from_date >= self.to_date:
            raise ValueError("from_date must be before to_date")
        span = (self.to_date - self.from_date).days
        if span > self.max_range_days:
            raise ValueError(
                f"requested range is {span} days; max is {self.max_range_days}. "
                "Raise max_range_days explicitly if the payload size is acceptable."
            )
        return self

    @model_validator(mode="after")
    def _validate_user_filter(self) -> Params:
        if self.user is not None and not self.user.strip():
            raise ValueError("user must be non-empty when provided")
        return self

    @model_validator(mode="after")
    def _validate_comparison(self) -> Params:
        if self.comparison_mode != "custom":
            return self
        if self.compare_from_date is None or self.compare_to_date is None:
            raise ValueError(
                "comparison_mode='custom' requires both compare_from_date and compare_to_date"
            )
        if self.compare_from_date >= self.compare_to_date:
            raise ValueError("compare_from_date must be before compare_to_date")
        return self


class TopChatterStat(BaseModel):
    user_id: str
    username: str
    messageCount: int
    activeDays: int
    firstSeen: str | None = None
    lastSeen: str | None = None
    engagement_score: float | None = None
    # Channels this user appeared in. Only populated for pooled multi-channel
    # runs; single-channel runs leave it empty.
    channels: list[str] = []


class DayCount(BaseModel):
    date: str
    count: int


class TrendPoint(BaseModel):
    date: str
    count: float


class WordCount(BaseModel):
    word: str
    count: int


class EmoteCount(BaseModel):
    name: str
    count: int


class EmotePairCount(BaseModel):
    emote1: str
    emote2: str
    count: int


class CommandCount(BaseModel):
    name: str
    count: int
    unique_users: int = 0


class DomainCount(BaseModel):
    domain: str
    count: int


class UrlCount(BaseModel):
    url: str
    count: int


class MentionCount(BaseModel):
    username: str
    count: int


class MentionPair(BaseModel):
    from_user: str
    to_user: str
    count: int


class MentionDegree(BaseModel):
    username: str
    mentions_in: int
    mentions_out: int
    degree: int


class MutualMentionPair(BaseModel):
    user_a: str
    user_b: str
    count_ab: int
    count_ba: int
    total: int


class EmoteCentrality(BaseModel):
    emote: str
    distinct_co_occurrences: int


class LorenzSample(BaseModel):
    top_pct: float
    message_share_pct: float


class BotScore(BaseModel):
    user_id: str
    username: str
    score: float
    signals: list[str]


class CohortCell(BaseModel):
    week_offset: int
    retention_pct: float


class CohortRow(BaseModel):
    cohort_week: str
    cohort_size: int
    retention: list[CohortCell]


class DayLanguage(BaseModel):
    date: str
    language: str
    percentage: float


class RepeatedMessage(BaseModel):
    text: str
    count: int


class RoleCount(BaseModel):
    role: str
    messages: int
    unique_users: int


class StaffMember(BaseModel):
    user_id: str
    username: str
    role: str
    messageCount: int
    firstSeen: str | None = None
    lastSeen: str | None = None


class SessionStats(BaseModel):
    total_sessions: int = 0
    avg_messages_per_session: float | None = None
    avg_session_minutes: float | None = None
    longest_session_minutes: float | None = None
    median_session_minutes: float | None = None
    p90_session_minutes: float | None = None


class Concentration(BaseModel):
    gini_coefficient: float | None = None
    top_10pct_share: float | None = None


class MessageClassStats(BaseModel):
    questions: int = 0
    exclamations: int = 0
    all_caps: int = 0
    emote_only: int = 0
    short_messages: int = 0
    long_messages: int = 0


class PhraseCount(BaseModel):
    phrase: str
    count: int


class PlatformLinks(BaseModel):
    twitch_clips: int = 0
    youtube: int = 0
    discord: int = 0
    x_twitter: int = 0
    kick: int = 0
    other: int = 0


class PeakStat(BaseModel):
    window_start: str
    message_count: int


class ChatterDist(BaseModel):
    p50: float | None = None
    p75: float | None = None
    p90: float | None = None
    p95: float | None = None
    p99: float | None = None


class ActivityPerDayStats(BaseModel):
    avg_active_chatters: float | None = None
    peak_active_chatters: int | None = None


class LanguageBreakdown(BaseModel):
    language: str
    percentage: float


class AnomalyStat(BaseModel):
    window_start: str
    message_count: int
    z_score: float
    p_value: float


class QuoteReplyPair(BaseModel):
    from_user: str
    to_user: str
    count: int


class EmoteDiversityStat(BaseModel):
    user_id: str
    username: str
    total_emote_uses: int
    unique_emotes: int
    diversity_ratio: float


class CopyPasteChain(BaseModel):
    text: str
    occurrences: int
    distinct_users: int


class ChannelSummary(BaseModel):
    """Compact per-channel view within a multi-channel run.

    Full per-channel stats would 3x the payload for redundant info. This
    carries the headline numbers plus the small lists a summary card needs.
    `messages_per_day` is aligned to the merged window's span so it can be
    plotted against the merged chart without offsetting.
    """

    channel: str
    total_messages: int
    unique_chatters: int
    top_chatters: list[TopChatterStat] = []
    top_emotes: list[EmoteCount] = []
    # Side-by-side compare lists — populated only for multi-channel runs.
    top_words: list[WordCount] = []
    top_commands: list[CommandCount] = []
    top_domains: list[DomainCount] = []
    top_mentions: list[MentionCount] = []
    roles: list[RoleCount] = []
    peak_concurrent_chatters: int | None = None
    messages_per_day: list[DayCount] = []
    first_message: str | None = None
    last_message: str | None = None


class ChatterDelta(BaseModel):
    """One chatter's movement between two comparable windows."""

    user_id: str
    username: str
    current: int
    previous: int
    delta: int


class PreviousPeriod(BaseModel):
    """Summary of the equivalent window immediately before the request.

    Scalar aggregates + small composition maps, so the payload cost stays
    bounded. Per-user deltas are precomputed server-side (top 5 gainers and
    losers) — the frontend has no way to reconstruct them from a lean summary.

    vocab_richness / unique_word_count stay None unless compute_overview
    grows them: the vocabulary stats need the emote-aware stopwords set and
    are not cheap to recompute here.
    """

    from_date: str
    to_date: str

    # Headline scalars (Phase 1)
    total_messages: int
    unique_chatters: int
    avg_message_length: float
    median_message_length: float | None = None
    max_message_length: int | None = None
    avg_words_per_message: float | None = None
    vocab_richness: float | None = None
    unique_word_count: int = 0
    peak_concurrent_chatters: int | None = None

    # Composition (Phase 2)
    roles: dict[str, int] = {}
    message_classes: dict[str, int] = {}
    platform_links: dict[str, int] = {}
    self_repetition_count: int = 0
    duplicate_message_count: int = 0
    non_ascii_ratio: float | None = None
    cross_user_copy_paste_count: int = 0

    # Top movers (Phase 2)
    top_chatter_gainers: list[ChatterDelta] = []
    top_chatter_losers: list[ChatterDelta] = []

    # Time-series (Phase 3) — aligned by *index* to the current window, not by
    # date. Day 0 of the previous window is the same offset as day 0 of the
    # current window, which is what makes the visual comparison meaningful.
    messages_per_day: list[DayCount] = []
    activity_by_hour: list[int] = Field(default_factory=lambda: [0] * 24)

    # Which window the backend resolved. Lets the UI show "vs previous week"
    # instead of a generic "vs previous period".
    mode: ComparisonMode = "previous_period"


class Result(BaseModel):
    total_messages: int
    unique_chatters: int
    days_spanned: int
    avg_message_length: float
    median_message_length: float | None = None
    max_message_length: int | None = None
    avg_words_per_message: float | None = None

    truncated: bool
    from_cache: bool = False
    cached_at: str | None = None

    top_chatters: list[TopChatterStat]
    activity_by_hour: list[int]
    activity_by_weekday_hour: list[list[int]]
    # One entry per calendar day in the requested range. Bounded by
    # Params.max_range_days (default 366).
    messages_per_day: list[DayCount]
    top_words: list[WordCount]
    top_emotes: list[EmoteCount]
    top_emote_pairs: list[EmotePairCount] = []

    messages_with_commands: int = 0
    top_commands: list[CommandCount] = []

    messages_with_links: int = 0
    top_domains: list[DomainCount] = []
    # Full URLs ranked by occurrence count (see analytics/links.compute_links).
    # Bounded by Params.top_n so payload stays small even for link-heavy ranges.
    top_urls: list[UrlCount] = []
    # Full ranked URL list for the "show all" dialog (capped at
    # links.MAX_ALL_URLS to bound payload). `unique_url_count` is the true
    # distinct count, so the UI can flag when the cap was hit.
    all_urls: list[UrlCount] = []
    unique_url_count: int = 0
    platform_links: PlatformLinks = Field(default_factory=PlatformLinks)

    messages_with_mentions: int = 0
    top_mentions: list[MentionCount] = []
    top_mention_pairs: list[MentionPair] = []

    duplicate_message_count: int = 0
    top_repeated_messages: list[RepeatedMessage] = []

    roles: list[RoleCount] = []
    staff_list: list[StaffMember] = []
    subscriber_list: list[StaffMember] = []
    subscriber_count: int = 0
    sessions: SessionStats = Field(default_factory=SessionStats)
    concentration: Concentration = Field(default_factory=Concentration)
    message_classes: MessageClassStats = Field(default_factory=MessageClassStats)
    top_phrases: list[PhraseCount] = []

    top_peaks_5m: list[PeakStat] = []
    chatter_message_quantiles: ChatterDist = Field(default_factory=ChatterDist)
    activity_per_day_stats: ActivityPerDayStats = Field(default_factory=ActivityPerDayStats)

    # Per-day arrays like messages_per_day above — same max_range_days bound.
    daily_new_chatters: list[DayCount] = []
    daily_returning_chatters: list[DayCount] = []
    language_breakdown: list[LanguageBreakdown] = []
    anomalies_5m: list[AnomalyStat] = []

    # Tier 1 additions — all defaulted so payloads stay backwards-compatible.
    # TTR (vocab_richness) is length-dependent: longer ranges read lower.
    peak_concurrent_chatters: int | None = None
    peak_concurrent_window: str | None = None
    vocab_richness: float | None = None
    unique_word_count: int = 0
    self_repetition_count: int = 0
    self_repetition_pct: float | None = None
    # Event count (inter-user handoffs) vs distinct texts with >= 1 event.
    cross_user_copy_paste_count: int = 0
    cross_user_copy_paste_texts: int = 0
    top_copy_paste_chains: list[CopyPasteChain] = []
    non_ascii_ratio: float | None = None
    messages_with_non_ascii: int = 0
    emote_diversity: list[EmoteDiversityStat] = []
    first_message_hours: list[int] = Field(default_factory=lambda: [0] * 24)

    # Tier 2 additions — all defaulted.
    mention_graph: list[MentionDegree] = []
    mutual_mention_pairs: list[MutualMentionPair] = []
    emote_centrality: list[EmoteCentrality] = []
    lorenz_samples: list[LorenzSample] = []
    emote_entropy: float | None = None
    bot_likelihood: list[BotScore] = []
    message_length_trend_slope: float | None = None
    cohort_retention: list[CohortRow] = []
    language_by_day: list[DayLanguage] = []

    # Tier 3 refinements (all defaulted).
    hapax_ratio: float | None = None
    zipf_slope: float | None = None
    trend_by_day: list[TrendPoint] = []
    weekly_seasonality: list[float] | None = None
    quote_reply_count: int = 0
    quote_reply_pairs: list[QuoteReplyPair] = []
    previous_period: PreviousPeriod | None = None
    channel_summaries: list[ChannelSummary] = []
    per_channel: list[ChannelResult] = []
    warnings: list[str] = []


class ChannelResult(Result):
    """Full isolated stats for one channel within a multi-channel run.

    Same shape as `Result` plus the channel name. `channel_summaries` and
    `per_channel` stay empty here so the frontend can treat it as a
    single-channel result; `previous_period` stays None to bound payload.
    """

    channel: str


# Resolve the forward reference in Result.per_channel.
Result.model_rebuild()
