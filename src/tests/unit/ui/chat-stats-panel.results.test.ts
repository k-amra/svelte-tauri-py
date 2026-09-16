import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/svelte';
import { backend } from '$lib/api/backend.svelte';
import ChatStatsPanel from '$lib/components/ChatStatsPanel.svelte';
import type { JobStatus } from '$lib/api/types';
import { fakeStats, doneJob, fillForm } from '../../helpers/chat-stats';

vi.mock('$lib/api/client', () => ({
	api: { createJob: vi.fn(), waitJob: vi.fn() }
}));

import { api } from '$lib/api/client';

const mockCreateJob = vi.mocked(api.createJob);
const mockWaitJob = vi.mocked(api.waitJob);

vi.mock('$lib/api/external', () => ({
	openExternal: vi.fn()
}));

import { openExternal } from '$lib/api/external';

const mockOpenExternal = vi.mocked(openExternal);

describe('ChatStatsPanel results', () => {
	beforeEach(async () => {
		vi.stubEnv('VITE_BACKEND_PORT', '9999');
		vi.stubEnv('VITE_BACKEND_TOKEN', 'test');
		mockCreateJob.mockReset();
		mockWaitJob.mockReset();
		mockOpenExternal.mockReset();
		await backend.dispose();
		await backend.init();
		expect(backend.ready).toBe(true);
	});

	afterEach(async () => {
		vi.unstubAllEnvs();
		await backend.dispose();
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
		await fillForm();
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
					include_copy_paste_chains: true,
					include_mention_graph: false,
					include_mutual_mentions: false,
					include_emote_centrality: false,
					include_emote_entropy: false,
					include_lorenz: false,
					include_bot_scores: false,
					include_length_trend: false,
					include_cohort_retention: false,
					include_quote_replies: false,
					include_subscriber_list: false,
					compare_previous: false
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
		expect(screen.getByText('Top links (by paste count)')).toBeInTheDocument();
		await fireEvent.click(screen.getByRole('button', { name: 'https://example.com/x' }));
		expect(mockOpenExternal).toHaveBeenCalledWith('https://example.com/x');
		expect(screen.getAllByText('Copy-paste chains').length).toBeGreaterThan(0);
		expect(screen.getByText('2 reposts / 1 texts')).toBeInTheDocument();
		expect(screen.getByText('raid incoming')).toBeInTheDocument();
		expect(
			screen.getByText('First message by hour (UTC, in-range first seen)')
		).toBeInTheDocument();
		expect(screen.getByText('Emote diversity (Twitch emotes, 5+ uses)')).toBeInTheDocument();
		expect(screen.getByText('test warning')).toBeInTheDocument();
		expect(screen.getByText('Weekly seasonality (vs trend)')).toBeInTheDocument();
		expect(screen.getByText(/hapax 0\.5/)).toBeInTheDocument();
		expect(screen.getByText('max length')).toBeInTheDocument();
		expect(screen.getByText('Mention graph (in/out degree)')).toBeInTheDocument();
		expect(screen.getByText('zed')).toBeInTheDocument();
		// Checkbox label + result header share the text.
		expect(screen.getAllByText('Mutual mentions')).toHaveLength(2);
		expect(screen.getByText('Emote centrality (distinct co-occurrences)')).toBeInTheDocument();
		expect(screen.getByText('PogChamp')).toBeInTheDocument();
		expect(screen.getByText('Lorenz curve (message share by top %)')).toBeInTheDocument();
		expect(screen.getByText('Bot likelihood (heuristic)')).toBeInTheDocument();
		expect(screen.getByText('botty')).toBeInTheDocument();
		expect(screen.getByText('Message length trend')).toBeInTheDocument();
		expect(screen.getByText('Weekly cohort retention (%)')).toBeInTheDocument();
		expect(screen.getByText('Top language per day')).toBeInTheDocument();
		expect(screen.getAllByText('Quote replies').length).toBeGreaterThan(0);
		expect(screen.getByText('1 inferred')).toBeInTheDocument();
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
		await fillForm();
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
		await fillForm();
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
		await fillForm();
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
		await fillForm();
		await fireEvent.click(screen.getByRole('button', { name: /run stats/i }));

		await waitFor(() => {
			expect(screen.getByTestId('cs-fresh')).toHaveTextContent('Freshly downloaded');
		});
	});
});
