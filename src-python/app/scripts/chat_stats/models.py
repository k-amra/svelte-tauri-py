"""Pydantic models for chat_stats Params / Result and every nested shape.

Field order is load-bearing for the JSON schema — do not reorder.
"""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class Params(BaseModel):
    channel: str
    channel_id_type: Literal["channel", "channelid"] = "channel"

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


class TopChatterStat(BaseModel):
    user_id: str
    username: str
    messageCount: int
    activeDays: int
    firstSeen: str | None = None
    lastSeen: str | None = None
    engagement_score: float | None = None


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
    platform_links: PlatformLinks = Field(default_factory=PlatformLinks)

    messages_with_mentions: int = 0
    top_mentions: list[MentionCount] = []
    top_mention_pairs: list[MentionPair] = []

    duplicate_message_count: int = 0
    top_repeated_messages: list[RepeatedMessage] = []

    roles: list[RoleCount] = []
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
    warnings: list[str] = []
