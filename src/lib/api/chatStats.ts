/**
 * Hand-written mirror of the `chat_stats` Pydantic `Result` + `Params`
 * (src-python/app/scripts/chat_stats.py). `types.ts` stays the generated
 * placeholder; this file tracks the one capability with a rich result shape.
 *
 * Keep in sync with Params/Result in chat_stats.py (v4.2).
 */
export interface TopChatterStat {
	user_id: string;
	username: string;
	messageCount: number;
	activeDays: number;
	firstSeen: string | null;
	lastSeen: string | null;
	engagement_score: number | null;
}

export interface DayCount {
	date: string;
	count: number;
}

export interface WordCount {
	word: string;
	count: number;
}

export interface EmoteCount {
	name: string;
	count: number;
}

export interface EmotePairCount {
	emote1: string;
	emote2: string;
	count: number;
}

export interface CommandCount {
	name: string;
	count: number;
	unique_users: number;
}

export interface DomainCount {
	domain: string;
	count: number;
}

export interface MentionCount {
	username: string;
	count: number;
}

export interface MentionPair {
	from_user: string;
	to_user: string;
	count: number;
}

export interface RepeatedMessage {
	text: string;
	count: number;
}

export interface RoleCount {
	role: string;
	messages: number;
	unique_users: number;
}

export interface SessionStats {
	total_sessions: number;
	avg_messages_per_session: number | null;
	avg_session_minutes: number | null;
	longest_session_minutes: number | null;
}

export interface Concentration {
	gini_coefficient: number | null;
	top_10pct_share: number | null;
}

export interface MessageClassStats {
	questions: number;
	exclamations: number;
	all_caps: number;
	emote_only: number;
	short_messages: number;
	long_messages: number;
}

export interface PhraseCount {
	phrase: string;
	count: number;
}

export interface PlatformLinks {
	twitch_clips: number;
	youtube: number;
	discord: number;
	x_twitter: number;
	kick: number;
	other: number;
}

export interface PeakStat {
	window_start: string;
	message_count: number;
}

export interface ChatterDist {
	p50: number | null;
	p75: number | null;
	p90: number | null;
	p95: number | null;
}

export interface ActivityPerDayStats {
	avg_active_chatters: number | null;
	peak_active_chatters: number | null;
}

export interface LanguageBreakdown {
	language: string;
	percentage: number;
}

export interface AnomalyStat {
	window_start: string;
	message_count: number;
	z_score: number;
}

export interface ChatStatsResult {
	total_messages: number;
	unique_chatters: number;
	days_spanned: number;
	avg_message_length: number;
	median_message_length: number | null;
	max_message_length: number | null;
	avg_words_per_message: number | null;
	truncated: boolean;
	/** True when the result came from the on-disk cache (no re-download). */
	from_cache: boolean;
	/** ISO timestamp of the original fetch when from_cache, else null. */
	cached_at: string | null;
	top_chatters: TopChatterStat[];
	/** 24 buckets, UTC hour of day. */
	activity_by_hour: number[];
	/** 7 rows (Monday-first) x 24 columns, UTC. */
	activity_by_weekday_hour: number[][];
	messages_per_day: DayCount[];
	top_words: WordCount[];
	top_emotes: EmoteCount[];
	top_emote_pairs: EmotePairCount[];

	messages_with_commands: number;
	top_commands: CommandCount[];

	messages_with_links: number;
	top_domains: DomainCount[];
	platform_links: PlatformLinks;

	messages_with_mentions: number;
	top_mentions: MentionCount[];
	top_mention_pairs: MentionPair[];

	duplicate_message_count: number;
	top_repeated_messages: RepeatedMessage[];

	roles: RoleCount[];
	sessions: SessionStats;
	concentration: Concentration;
	message_classes: MessageClassStats;
	top_phrases: PhraseCount[];

	top_peaks_5m: PeakStat[];
	chatter_message_quantiles: ChatterDist;
	activity_per_day_stats: ActivityPerDayStats;

	daily_new_chatters: DayCount[];
	daily_returning_chatters: DayCount[];
	language_breakdown: LanguageBreakdown[];
	anomalies_5m: AnomalyStat[];
}

export interface ChatStatsParams {
	channel: string;
	channel_id_type: 'channel' | 'channelid';
	from_date: string;
	to_date: string;
	top_n: number;
	top_words_n: number;
	top_emotes_n: number;
	top_phrases_n: number;
	include_commands: boolean;
	include_links: boolean;
	include_mentions: boolean;
	include_duplicates: boolean;
	include_phrases: boolean;
	include_sessions: boolean;
	include_concentration: boolean;
	include_message_class: boolean;
	include_new_returning: boolean;
	include_emote_pairs: boolean;
	include_engagement: boolean;
	include_anomalies: boolean;
	include_language: boolean;
	session_gap_minutes: number;
	anomaly_sigma: number;
	force_refresh: boolean;
}

export const WEEKDAY_LABELS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
