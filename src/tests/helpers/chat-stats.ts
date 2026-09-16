import { screen, fireEvent } from '@testing-library/svelte';
import type { ChatStatsResult } from '$lib/api/chatStats';
import type { JobStatus } from '$lib/api/types';

export const fakeStats: ChatStatsResult = {
	total_messages: 42,
	unique_chatters: 7,
	days_spanned: 3,
	avg_message_length: 12.5,
	median_message_length: 10,
	max_message_length: 120,
	avg_words_per_message: 3.2,
	truncated: false,
	from_cache: false,
	cached_at: null,
	top_chatters: [
		{
			user_id: 'u1',
			username: 'alice',
			messageCount: 30,
			activeDays: 3,
			firstSeen: '2024-01-15T10:00:00+00:00',
			lastSeen: '2024-01-17T10:00:00+00:00',
			engagement_score: 0.95
		},
		{
			user_id: 'u2',
			username: 'bob',
			messageCount: 12,
			activeDays: 2,
			firstSeen: '2024-01-15T11:00:00+00:00',
			lastSeen: '2024-01-16T11:00:00+00:00',
			engagement_score: 0.5
		}
	],
	activity_by_hour: Array.from({ length: 24 }, (_, h) => (h === 10 ? 42 : 0)),
	activity_by_weekday_hour: Array.from({ length: 7 }, (_, d) =>
		Array.from({ length: 24 }, (_, h) => (d === 0 && h === 10 ? 42 : 0))
	),
	messages_per_day: [{ date: '2024-01-15', count: 42 }],
	top_words: [{ word: 'hello', count: 20 }],
	top_emotes: [{ name: 'Kappa', count: 15 }],
	top_emote_pairs: [{ emote1: 'Kappa', emote2: 'KEKW', count: 5 }],
	messages_with_commands: 8,
	top_commands: [{ name: 'shoutout', count: 8, unique_users: 3 }],
	messages_with_links: 4,
	top_domains: [{ domain: 'example.com', count: 4 }],
	top_urls: [
		{ url: 'https://example.com/x', count: 3 },
		{ url: 'https://other.org/y', count: 1 }
	],
	all_urls: [
		{ url: 'https://example.com/x', count: 3 },
		{ url: 'https://other.org/y', count: 1 }
	],
	unique_url_count: 2,
	platform_links: {
		twitch_clips: 1,
		youtube: 1,
		discord: 1,
		x_twitter: 0,
		kick: 0,
		other: 1
	},
	messages_with_mentions: 6,
	top_mentions: [{ username: 'bob', count: 6 }],
	top_mention_pairs: [{ from_user: 'alice', to_user: 'bob', count: 4 }],
	duplicate_message_count: 2,
	top_repeated_messages: [{ text: 'hello', count: 3 }],
	roles: [{ role: 'regular', messages: 40, unique_users: 7 }],
	staff_list: [
		{
			user_id: '2',
			username: 'mod1',
			role: 'moderator',
			messageCount: 12,
			firstSeen: '2025-01-01T00:01:00+00:00',
			lastSeen: '2025-01-02T00:01:00+00:00'
		}
	],
	subscriber_list: [],
	subscriber_count: 0,
	previous_period: null,
	channel_summaries: [],
	per_channel: [],
	sessions: {
		total_sessions: 2,
		avg_messages_per_session: 21,
		avg_session_minutes: 30,
		longest_session_minutes: 45,
		median_session_minutes: 25,
		p90_session_minutes: 40
	},
	concentration: { gini_coefficient: 0.4, top_10pct_share: 55.5 },
	message_classes: {
		questions: 5,
		exclamations: 7,
		all_caps: 2,
		emote_only: 3,
		short_messages: 4,
		long_messages: 1
	},
	top_phrases: [],
	top_peaks_5m: [{ window_start: '2024-01-15T10:00:00+00:00', message_count: 20 }],
	chatter_message_quantiles: { p50: 5, p75: 10, p90: 20, p95: 28, p99: 30 },
	activity_per_day_stats: { avg_active_chatters: 4.5, peak_active_chatters: 7 },
	daily_new_chatters: [{ date: '2024-01-15', count: 7 }],
	daily_returning_chatters: [{ date: '2024-01-16', count: 2 }],
	language_breakdown: [],
	anomalies_5m: [],
	peak_concurrent_chatters: 6,
	peak_concurrent_window: '2024-01-15T10:00:00+00:00',
	vocab_richness: 0.42,
	unique_word_count: 100,
	self_repetition_count: 3,
	self_repetition_pct: 7.14,
	cross_user_copy_paste_count: 2,
	cross_user_copy_paste_texts: 1,
	top_copy_paste_chains: [{ text: 'raid incoming', occurrences: 2, distinct_users: 3 }],
	non_ascii_ratio: 0.05,
	messages_with_non_ascii: 2,
	emote_diversity: [
		{
			user_id: 'u3',
			username: 'carol',
			total_emote_uses: 10,
			unique_emotes: 4,
			diversity_ratio: 0.4
		}
	],
	mention_graph: [{ username: 'zed', mentions_in: 2, mentions_out: 1, degree: 3 }],
	mutual_mention_pairs: [{ user_a: 'amy', user_b: 'zed', count_ab: 2, count_ba: 1, total: 3 }],
	emote_centrality: [{ emote: 'PogChamp', distinct_co_occurrences: 4 }],
	lorenz_samples: [{ top_pct: 10, message_share_pct: 55.5 }],
	emote_entropy: 1.5,
	bot_likelihood: [
		{ user_id: 'u9', username: 'botty', score: 0.8, signals: ['regular_interval', 'low_diversity'] }
	],
	message_length_trend_slope: -0.42,
	cohort_retention: [
		{
			cohort_week: '2024-01-15',
			cohort_size: 7,
			retention: [{ week_offset: 0, retention_pct: 100 }]
		}
	],
	language_by_day: [{ date: '2024-01-15', language: 'en', percentage: 90 }],
	first_message_hours: Array.from({ length: 24 }, (_, h) => (h === 10 ? 5 : 0)),
	hapax_ratio: 0.5,
	zipf_slope: -0.9,
	trend_by_day: [{ date: '2024-01-15', count: 42 }],
	weekly_seasonality: [1, 1, 1, 1, 1, 1.15, 0.85],
	quote_reply_count: 1,
	quote_reply_pairs: [{ from_user: 'alice', to_user: 'bob', count: 1 }],
	warnings: ['test warning']
};

export async function fillChannel() {
	const channel = screen.getByPlaceholderText('e.g., demonzz1') as HTMLInputElement;
	await fireEvent.input(channel, { target: { value: 'demonzz1' } });
}

export async function fillForm() {
	await fillChannel();
	const from = document.getElementById('cs-from') as HTMLInputElement;
	const to = document.getElementById('cs-to') as HTMLInputElement;
	await fireEvent.input(from, { target: { value: '2024-01-01T10:00' } });
	await fireEvent.input(to, { target: { value: '2024-01-02T10:00' } });
}

export function doneJob(): JobStatus {
	return {
		job_id: 'abc123',
		script: 'chat_stats',
		status: 'done',
		progress: 100,
		message: 'done',
		result: fakeStats,
		error: null
	};
}
