import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/svelte';
import { backend } from '$lib/api/backend.svelte';
import ChatStatsPanel from '$lib/components/ChatStatsPanel.svelte';
import { fakeStats, doneJob, fillForm } from '../../helpers/chat-stats';

vi.mock('$lib/api/client', () => ({
	api: { createJob: vi.fn(), waitJob: vi.fn() }
}));

import { api } from '$lib/api/client';

const mockCreateJob = vi.mocked(api.createJob);
const mockWaitJob = vi.mocked(api.waitJob);

describe('ChatStatsPanel tabs', () => {
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

	it('switches between pooled and per-channel tabs without a second job', async () => {
		const pooled = {
			...fakeStats,
			total_messages: 42,
			per_channel: [
				{
					...fakeStats,
					channel: 'aaa',
					total_messages: 30,
					channel_summaries: [],
					per_channel: []
				},
				{ ...fakeStats, channel: 'bbb', total_messages: 12, channel_summaries: [], per_channel: [] }
			]
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
		mockWaitJob.mockResolvedValueOnce({ ...doneJob(), result: pooled });

		render(ChatStatsPanel);
		await fillForm();
		await fireEvent.click(screen.getByRole('button', { name: /run stats/i }));

		await waitFor(() => {
			expect(screen.getByRole('button', { name: 'Pooled (All Channels)' })).toBeInTheDocument();
		});
		expect(screen.getByRole('button', { name: 'aaa' })).toBeInTheDocument();
		expect(screen.getByTestId('cs-total')).toHaveTextContent('42');

		await fireEvent.click(screen.getByRole('button', { name: 'aaa' }));
		await waitFor(() => {
			expect(screen.getByTestId('cs-total')).toHaveTextContent('30');
		});
		// No second backend run for a view-only tab switch.
		expect(mockCreateJob).toHaveBeenCalledTimes(1);

		await fireEvent.click(screen.getByRole('button', { name: 'bbb' }));
		await waitFor(() => {
			expect(screen.getByTestId('cs-total')).toHaveTextContent('12');
		});
	});

	it('channel-card drill switches to the cached per-channel tab without a new job', async () => {
		const pooled = {
			...fakeStats,
			total_messages: 42,
			channel_summaries: [
				{
					channel: 'aaa',
					total_messages: 30,
					unique_chatters: 5,
					top_chatters: [],
					top_emotes: [],
					top_words: [],
					top_commands: [],
					top_domains: [],
					top_mentions: [],
					roles: [],
					peak_concurrent_chatters: null,
					messages_per_day: [],
					first_message: null,
					last_message: null
				},
				{
					channel: 'bbb',
					total_messages: 12,
					unique_chatters: 2,
					top_chatters: [],
					top_emotes: [],
					top_words: [],
					top_commands: [],
					top_domains: [],
					top_mentions: [],
					roles: [],
					peak_concurrent_chatters: null,
					messages_per_day: [],
					first_message: null,
					last_message: null
				}
			],
			per_channel: [
				{
					...fakeStats,
					channel: 'aaa',
					total_messages: 30,
					channel_summaries: [],
					per_channel: []
				},
				{
					...fakeStats,
					channel: 'bbb',
					total_messages: 12,
					channel_summaries: [],
					per_channel: []
				}
			]
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
		mockWaitJob.mockResolvedValueOnce({ ...doneJob(), result: pooled });

		render(ChatStatsPanel);
		await fillForm();
		await fireEvent.click(screen.getByRole('button', { name: /run stats/i }));

		await waitFor(() => {
			expect(screen.getByTestId('cs-total')).toHaveTextContent('42');
		});
		await fireEvent.click(screen.getByTitle('aaa — click to scope all stats to this channel'));
		await waitFor(() => {
			expect(screen.getByTestId('cs-total')).toHaveTextContent('30');
		});
		// Served from the in-memory per_channel result — no second job.
		expect(mockCreateJob).toHaveBeenCalledTimes(1);
	});

	it('badges pooled top chatters with their channels and keeps the tab bar sticky', async () => {
		const pooled = {
			...fakeStats,
			total_messages: 42,
			top_chatters: [
				{ ...fakeStats.top_chatters[0], channels: ['aaa', 'bbb'] },
				{ ...fakeStats.top_chatters[1], channels: ['aaa'] }
			],
			channel_summaries: [
				{
					channel: 'aaa',
					total_messages: 30,
					unique_chatters: 5,
					top_chatters: [],
					top_emotes: [],
					top_words: [],
					top_commands: [],
					top_domains: [],
					top_mentions: [],
					roles: [],
					peak_concurrent_chatters: null,
					messages_per_day: [],
					first_message: null,
					last_message: null
				},
				{
					channel: 'bbb',
					total_messages: 12,
					unique_chatters: 2,
					top_chatters: [],
					top_emotes: [],
					top_words: [],
					top_commands: [],
					top_domains: [],
					top_mentions: [],
					roles: [],
					peak_concurrent_chatters: null,
					messages_per_day: [],
					first_message: null,
					last_message: null
				}
			],
			per_channel: [
				{
					...fakeStats,
					channel: 'aaa',
					total_messages: 30,
					channel_summaries: [],
					per_channel: []
				},
				{
					...fakeStats,
					channel: 'bbb',
					total_messages: 12,
					channel_summaries: [],
					per_channel: []
				}
			]
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
		mockWaitJob.mockResolvedValueOnce({ ...doneJob(), result: pooled });

		render(ChatStatsPanel);
		await fillForm();
		await fireEvent.click(screen.getByRole('button', { name: /run stats/i }));

		await waitFor(() => {
			expect(screen.getByTitle('Active in: aaa, bbb')).toHaveTextContent('aaa·bbb');
		});
		expect(screen.getByTitle('Active in: aaa')).toHaveTextContent('aaa');
		// Sticky tab bar stays pinned above the section nav.
		const tabBar = screen.getByRole('button', { name: 'Pooled (All Channels)' }).parentElement;
		expect(tabBar?.className).toContain('sticky');
		expect(screen.getByRole('navigation', { name: 'Result sections' }).className).toContain(
			'top-11'
		);
	});
});
