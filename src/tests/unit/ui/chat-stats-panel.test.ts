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
	truncated: false,
	top_chatters: [
		{ username: 'alice', messageCount: 30 },
		{ username: 'bob', messageCount: 12 }
	],
	activity_by_hour: Array.from({ length: 24 }, (_, h) => (h === 10 ? 42 : 0)),
	activity_by_weekday_hour: Array.from({ length: 7 }, (_, d) =>
		Array.from({ length: 24 }, (_, h) => (d === 0 && h === 10 ? 42 : 0))
	),
	messages_per_day: [{ date: '2024-01-15', count: 42 }],
	top_words: [{ word: 'hello', count: 20 }]
};

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
		await fireEvent.click(screen.getByRole('button', { name: /run stats/i }));

		await waitFor(() => {
			expect(mockCreateJob).toHaveBeenCalledWith(
				'chat_stats',
				expect.objectContaining({ channel: 'demonzz1', top_n: 20 })
			);
		});
		await waitFor(() => {
			expect(screen.getByTestId('cs-total')).toHaveTextContent('42');
		});
		expect(screen.getByText('alice')).toBeInTheDocument();
		expect(screen.getByText('Weekday × hour heatmap (UTC)')).toBeInTheDocument();
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
});
