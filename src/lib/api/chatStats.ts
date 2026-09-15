/**
 * Hand-written mirror of the `chat_stats` Pydantic `Result` + `Params`
 * (src-python/app/scripts/chat_stats/models.py). `types.ts` stays the generated
 * placeholder; this file tracks the one capability with a rich result shape.
 *
 * Keep in sync with Params/Result in chat_stats/models.py (v4.5).
 */
export interface TopChatterStat {
	user_id: string;
	username: string;
	messageCount: number;
	activeDays: number;
	firstSeen: string | null;
	lastSeen: string | null;
	engagement_score: number | null;
	/**
	 * Channels this user appeared in. Only populated for pooled multi-channel
	 * runs; single-channel runs leave it empty. The frontend renders a badge
	 * from this list when viewing the pooled result.
	 */
	channels?: string[];
}

export interface DayCount {
	date: string;
	count: number;
}

export interface TrendPoint {
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

export interface EmoteDiversityStat {
	user_id: string;
	username: string;
	total_emote_uses: number;
	unique_emotes: number;
	diversity_ratio: number;
}

export interface CopyPasteChain {
	text: string;
	occurrences: number;
	distinct_users: number;
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

export interface UrlCount {
	url: string;
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

export interface ChatterDelta {
	user_id: string;
	username: string;
	current: number;
	previous: number;
	delta: number;
}

export interface ChannelSummary {
	channel: string;
	total_messages: number;
	unique_chatters: number;
	top_chatters: TopChatterStat[];
	top_emotes: EmoteCount[];
	top_words: WordCount[];
	top_commands: CommandCount[];
	top_domains: DomainCount[];
	top_mentions: MentionCount[];
	roles: RoleCount[];
	peak_concurrent_chatters: number | null;
	messages_per_day: DayCount[];
	first_message: string | null;
	last_message: string | null;
}

export type ComparisonMode =
	'previous_period' | 'previous_week' | 'previous_month' | 'previous_year' | 'custom';

/** Human label for the comparison mode, used in captions ("vs previous week"). */
export function comparisonModeLabel(mode: ComparisonMode): string {
	switch (mode) {
		case 'previous_week':
			return 'vs previous week';
		case 'previous_month':
			return 'vs previous month';
		case 'previous_year':
			return 'vs previous year';
		case 'custom':
			return 'vs custom range';
		default:
			return 'vs previous period';
	}
}

export interface PreviousPeriod {
	from_date: string;
	to_date: string;
	// Headline scalars
	total_messages: number;
	unique_chatters: number;
	avg_message_length: number;
	median_message_length: number | null;
	max_message_length: number | null;
	avg_words_per_message: number | null;
	vocab_richness: number | null;
	unique_word_count: number;
	peak_concurrent_chatters: number | null;
	// Composition
	roles: Record<string, number>;
	message_classes: Record<string, number>;
	platform_links: Record<string, number>;
	self_repetition_count: number;
	duplicate_message_count: number;
	non_ascii_ratio: number | null;
	cross_user_copy_paste_count: number;
	// Top movers
	top_chatter_gainers: ChatterDelta[];
	top_chatter_losers: ChatterDelta[];
	// Time-series, aligned by index to the current window
	messages_per_day: DayCount[];
	activity_by_hour: number[];
	/** Which window the backend resolved. Drives the caption in the UI. */
	mode: ComparisonMode;
}

export interface StaffMember {
	user_id: string;
	username: string;
	role: string;
	messageCount: number;
	firstSeen: string | null;
	lastSeen: string | null;
}

export interface SessionStats {
	total_sessions: number;
	avg_messages_per_session: number | null;
	avg_session_minutes: number | null;
	longest_session_minutes: number | null;
	median_session_minutes: number | null;
	p90_session_minutes: number | null;
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
	p99: number | null;
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
	p_value: number;
}

export interface MentionDegree {
	username: string;
	mentions_in: number;
	mentions_out: number;
	degree: number;
}

export interface MutualMentionPair {
	user_a: string;
	user_b: string;
	count_ab: number;
	count_ba: number;
	total: number;
}

export interface EmoteCentrality {
	emote: string;
	distinct_co_occurrences: number;
}

export interface LorenzSample {
	top_pct: number;
	message_share_pct: number;
}

export interface BotScore {
	user_id: string;
	username: string;
	score: number;
	signals: string[];
}

export interface CohortCell {
	week_offset: number;
	retention_pct: number;
}

export interface CohortRow {
	cohort_week: string;
	cohort_size: number;
	retention: CohortCell[];
}

export interface DayLanguage {
	date: string;
	language: string;
	percentage: number;
}

export interface QuoteReplyPair {
	from_user: string;
	to_user: string;
	count: number;
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
	top_urls: UrlCount[];
	/** Full ranked URL list for the "show all" dialog (capped at 5000). */
	all_urls: UrlCount[];
	/** True distinct URL count, even when `all_urls` is capped. */
	unique_url_count: number;
	platform_links: PlatformLinks;

	messages_with_mentions: number;
	top_mentions: MentionCount[];
	top_mention_pairs: MentionPair[];

	duplicate_message_count: number;
	top_repeated_messages: RepeatedMessage[];

	roles: RoleCount[];
	staff_list: StaffMember[];
	subscriber_list: StaffMember[];
	subscriber_count: number;
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

	peak_concurrent_chatters: number | null;
	peak_concurrent_window: string | null;
	/** Raw type-token ratio; length-dependent (longer ranges read lower). */
	vocab_richness: number | null;
	unique_word_count: number;
	self_repetition_count: number;
	self_repetition_pct: number | null;
	cross_user_copy_paste_count: number;
	cross_user_copy_paste_texts: number;
	top_copy_paste_chains: CopyPasteChain[];
	non_ascii_ratio: number | null;
	messages_with_non_ascii: number;
	emote_diversity: EmoteDiversityStat[];
	first_message_hours: number[];

	mention_graph: MentionDegree[];
	mutual_mention_pairs: MutualMentionPair[];
	emote_centrality: EmoteCentrality[];
	lorenz_samples: LorenzSample[];
	emote_entropy: number | null;
	bot_likelihood: BotScore[];
	message_length_trend_slope: number | null;
	cohort_retention: CohortRow[];
	language_by_day: DayLanguage[];

	hapax_ratio: number | null;
	zipf_slope: number | null;
	trend_by_day: TrendPoint[];
	weekly_seasonality: number[] | null;
	quote_reply_count: number;
	quote_reply_pairs: QuoteReplyPair[];
	previous_period: PreviousPeriod | null;
	channel_summaries: ChannelSummary[];
	per_channel: ChannelStatsResult[];
	warnings: string[];
}

/** Full isolated stats for one channel within a multi-channel run. */
export interface ChannelStatsResult extends ChatStatsResult {
	channel: string;
}

export interface ChatStatsParams {
	/** Deprecated: use `channels`. Kept for backwards compat. */
	channel?: string;
	/** One or more channels (up to 3); multi-channel runs pool their messages. */
	channels?: string[];
	channel_id_type: 'channel' | 'channelid';
	/** Optional single-user filter. Omit or leave undefined for whole-channel. */
	user?: string;
	/** Which column the `user` value matches. Defaults to 'user' on the backend. */
	user_id_type?: 'user' | 'userid';
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
	include_copy_paste_chains: boolean;
	// Tier 2 toggles are optional: the backend defaults them all to false,
	// so callers that don't pass them simply get Tier 1 behavior.
	include_mention_graph?: boolean;
	include_mutual_mentions?: boolean;
	include_emote_centrality?: boolean;
	include_emote_entropy?: boolean;
	include_lorenz?: boolean;
	include_bot_scores?: boolean;
	include_length_trend?: boolean;
	include_cohort_retention?: boolean;
	include_language_by_day?: boolean;
	include_quote_replies?: boolean;
	include_staff_list?: boolean;
	include_subscriber_list?: boolean;
	compare_previous?: boolean;
	comparison_mode?: ComparisonMode;
	compare_from_date?: string;
	compare_to_date?: string;
	session_gap_minutes: number;
	anomaly_sigma: number;
	force_refresh: boolean;
	max_range_days: number;
}

export const WEEKDAY_LABELS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
