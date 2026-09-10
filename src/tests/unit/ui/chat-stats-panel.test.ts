import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/svelte';
import { backend } from '$lib/api/backend.svelte';
import ChatStatsPanel from '$lib/components/ChatStatsPanel.svelte';
import type { ChatStatsResult } from '$lib/api/chatStats';
import type { JobStatus } from '$lib/api/types';

vi.mock('$lib/api/client', () => ({
	api: { createJob: vi.fn(), waitJob: vi.fn() }
}));

import { api } from '$lib/api/client';

const mockCreateJob = vi.mocked(api.createJob);
const mockWaitJob = vi.mocked(api.waitJob);

const fakeStats: ChatStatsResult = {
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
	sessions: {
		total_sessions: 2,
		avg_messages_per_session: 21,
		avg_session_minutes: 30,
		longest_session_minutes: 45
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
	chatter_message_quantiles: { p50: 5, p75: 10, p90: 20, p95: 28 },
	activity_per_day_stats: { avg_active_chatters: 4.5, peak_active_chatters: 7 },
	daily_new_chatters: [{ date: '2024-01-15', count: 7 }],
	daily_returning_chatters: [{ date: '2024-01-16', count: 2 }],
	language_breakdown: [],
	anomalies_5m: []
};

async function fillDates() {
	const from = document.getElementById('cs-from') as HTMLInputElement;
	const to = document.getElementById('cs-to') as HTMLInputElement;
	await fireEvent.input(from, { target: { value: '2024-01-01T10:00' } });
	await fireEvent.input(to, { target: { value: '2024-01-02T10:00' } });
}

function doneJob(): JobStatus {
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

describe('ChatStatsPanel', () => {
	beforeEach(async () => {
		vi.stubEnv('VITE_BACKEND_PORT', '9999');
		vi.stubEnv('VITE_BACKEND_TOKEN', 'test');
		mockCreateJob.mockReset();
		mockWaitJob.mockReset();
		await backend.dispose();
		await backend.init();
		expect(backend.ready).toBe(true);
	});

	afterEach(async () => {
		vi.unstubAllEnvs();
		await backend.dispose();
	});

	it('renders the form with defaults', () => {
		render(ChatStatsPanel);
		expect(screen.getByPlaceholderText('e.g., demonzz1')).toHaveValue('demonzz1');
		expect(screen.getByRole('button', { name: /run stats/i })).toBeInTheDocument();
	});

	it('runs a job and renders progress then results', async () => {
		mockCreateJob.mockResolvedValueOnce({
			job_id: 'abc123',
			script: 'chat_stats',
			status: 'running',
			progress: 0,
			message: '',
			result: null,
			error: null
		});
		mockWaitJob.mockImplementationOnce(async (_id, onProgress) => {
			onProgress?.({
				job_id: 'abc123',
				script: 'chat_stats',
				status: 'running',
				progress: 50,
				message: 'fetching',
				result: null,
				error: null
			});
			return doneJob();
		});

		render(ChatStatsPanel);
		await fillDates();
		await fireEvent.click(screen.getByRole('button', { name: /run stats/i }));

		await waitFor(() => {
			expect(mockCreateJob).toHaveBeenCalledWith(
				'chat_stats',
				expect.objectContaining({
					channel: 'demonzz1',
					top_n: 20,
					top_words_n: 50,
					top_emotes_n: 50,
					include_commands: true,
					include_language: false
				})
			);
		});
		await waitFor(() => {
			expect(screen.getByTestId('cs-total')).toHaveTextContent('42');
		});
		expect(screen.getByText('alice')).toBeInTheDocument();
		expect(screen.getByText('Weekday × hour heatmap (UTC)')).toBeInTheDocument();
		expect(screen.getByText('Top emotes')).toBeInTheDocument();
		expect(screen.getByText('Kappa')).toBeInTheDocument();
		expect(screen.getByText('Top emote pairs')).toBeInTheDocument();
		expect(screen.getByText(/Top commands/)).toBeInTheDocument();
	});

	it('labels the download phase in plain language', async () => {
		mockCreateJob.mockResolvedValueOnce({
			job_id: 'abc123',
			script: 'chat_stats',
			status: 'running',
			progress: 0,
			message: '',
			result: null,
			error: null
		});
		let seen: JobStatus | null = null;
		mockWaitJob.mockImplementationOnce(async (_id, onProgress) => {
			const running: JobStatus = {
				job_id: 'abc123',
				script: 'chat_stats',
				status: 'running',
				progress: 30,
				message: 'fetched 100 messages (page 2)',
				result: null,
				error: null
			};
			seen = running;
			onProgress?.(running);
			// Keep the job "running" so the phase stays visible for the assertion.
			await new Promise((resolve) => setTimeout(resolve, 50));
			return doneJob();
		});

		render(ChatStatsPanel);
		await fillDates();
		await fireEvent.click(screen.getByRole('button', { name: /run stats/i }));

		await waitFor(() => {
			expect(screen.getByTestId('cs-phase')).toHaveTextContent('Downloading chat logs…');
		});
		expect(screen.getByTestId('cs-phase-detail')).toHaveTextContent(
			'fetched 100 messages (page 2)'
		);
		expect(seen).not.toBeNull();
	});

	it('labels a month download as a download, not a redownload', async () => {
		mockCreateJob.mockResolvedValueOnce({
			job_id: 'abc123',
			script: 'chat_stats',
			status: 'running',
			progress: 0,
			message: '',
			result: null,
			error: null
		});
		mockWaitJob.mockImplementationOnce(async (_id, onProgress) => {
			onProgress?.({
				job_id: 'abc123',
				script: 'chat_stats',
				status: 'running',
				progress: 2,
				message: 'downloading 2024-09…',
				result: null,
				error: null
			});
			await new Promise((resolve) => setTimeout(resolve, 50));
			return doneJob();
		});

		render(ChatStatsPanel);
		await fillDates();
		await fireEvent.click(screen.getByRole('button', { name: /run stats/i }));

		await waitFor(() => {
			expect(screen.getByTestId('cs-phase')).toHaveTextContent('Downloading chat logs…');
		});
		expect(screen.getByTestId('cs-phase-detail')).toHaveTextContent('downloading 2024-09…');
	});

	it('shows the cache note and sends force_refresh when bypass is ticked', async () => {
		const cached: JobStatus = {
			...doneJob(),
			result: { ...fakeStats, from_cache: true, cached_at: '2024-01-15T10:30:00+00:00' }
		};
		mockCreateJob.mockResolvedValueOnce({
			job_id: 'abc123',
			script: 'chat_stats',
			status: 'running',
			progress: 0,
			message: '',
			result: null,
			error: null
		});
		mockWaitJob.mockResolvedValueOnce(cached);

		render(ChatStatsPanel);
		await fillDates();
		await fireEvent.click(screen.getByText('Bypass cache (re-download)'));
		await fireEvent.click(screen.getByRole('button', { name: /run stats/i }));

		await waitFor(() => {
			expect(mockCreateJob).toHaveBeenCalledWith(
				'chat_stats',
				expect.objectContaining({ force_refresh: true })
			);
		});
		await waitFor(() => {
			expect(screen.getByText(/Loaded from local cache/)).toBeInTheDocument();
		});
	});

	it('notes a fresh download on a non-cached result', async () => {
		mockCreateJob.mockResolvedValueOnce({
			job_id: 'abc123',
			script: 'chat_stats',
			status: 'running',
			progress: 0,
			message: '',
			result: null,
			error: null
		});
		mockWaitJob.mockResolvedValueOnce(doneJob());

		render(ChatStatsPanel);
		await fillDates();
		await fireEvent.click(screen.getByRole('button', { name: /run stats/i }));

		await waitFor(() => {
			expect(screen.getByTestId('cs-fresh')).toHaveTextContent('Freshly downloaded');
		});
	});

	it('requires a channel before spending a job', async () => {
		render(ChatStatsPanel);
		const input = screen.getByPlaceholderText('e.g., demonzz1');
		await fireEvent.input(input, { target: { value: '   ' } });
		await fireEvent.click(screen.getByRole('button', { name: /run stats/i }));

		await waitFor(() => {
			expect(screen.getByText('Channel is required.')).toBeInTheDocument();
		});
		expect(mockCreateJob).not.toHaveBeenCalled();
	});

	it('requires both dates (upstream rejects open ranges)', async () => {
		render(ChatStatsPanel);
		await fireEvent.click(screen.getByRole('button', { name: /run stats/i }));

		await waitFor(() => {
			expect(screen.getByText('Both from and to dates are required.')).toBeInTheDocument();
		});
		expect(mockCreateJob).not.toHaveBeenCalled();
	});

	it('rejects from >= to', async () => {
		render(ChatStatsPanel);
		// datetime-local inputs have no placeholder; grab by id
		const from = document.getElementById('cs-from') as HTMLInputElement;
		const to = document.getElementById('cs-to') as HTMLInputElement;
		await fireEvent.input(from, { target: { value: '2024-02-01T10:00' } });
		await fireEvent.input(to, { target: { value: '2024-01-01T10:00' } });
		await fireEvent.click(screen.getByRole('button', { name: /run stats/i }));

		await waitFor(() => {
			expect(screen.getByText('The from-date must be before the to-date.')).toBeInTheDocument();
		});
		expect(mockCreateJob).not.toHaveBeenCalled();
	});

	it('validates the new numeric options', async () => {
		render(ChatStatsPanel);
		await fillDates();
		const topWords = document.getElementById('cs-topwords') as HTMLInputElement;
		await fireEvent.input(topWords, { target: { value: '5' } });
		await fireEvent.click(screen.getByRole('button', { name: /run stats/i }));

		await waitFor(() => {
			expect(
				screen.getByText('Top words must be an integer between 10 and 200.')
			).toBeInTheDocument();
		});
		expect(mockCreateJob).not.toHaveBeenCalled();
	});
});
