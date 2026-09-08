/**
 * Hand-written mirror of the `chat_stats` Pydantic `Result`
 * (src-python/app/scripts/chat_stats.py). `types.ts` stays the generated
 * placeholder; this file tracks the one capability with a rich result shape.
 */
export interface TopChatterStat {
	username: string;
	messageCount: number;
}

export interface DayCount {
	date: string;
	count: number;
}

export interface WordCount {
	word: string;
	count: number;
}

export interface ChatStatsResult {
	total_messages: number;
	unique_chatters: number;
	days_spanned: number;
	avg_message_length: number;
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
}

export const WEEKDAY_LABELS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
