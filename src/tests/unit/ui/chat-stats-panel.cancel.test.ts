import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/svelte';
import { backend } from '$lib/api/backend.svelte';
import ChatStatsPanel from '$lib/components/ChatStatsPanel.svelte';
import { fillForm } from '../../helpers/chat-stats';

vi.mock('$lib/api/client', () => ({
	api: { createJob: vi.fn(), waitJob: vi.fn() },
	JobCancelledError: class JobCancelledError extends Error {
		constructor(jobId: string) {
			super(`job ${jobId} cancelled`);
			this.name = 'JobCancelledError';
		}
	}
}));

import { api, JobCancelledError } from '$lib/api/client';

const mockCreateJob = vi.mocked(api.createJob);
const mockWaitJob = vi.mocked(api.waitJob);

describe('ChatStatsPanel cancel', () => {
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

	it('cancelling a run detaches the waiter with a cancelled message', async () => {
		mockCreateJob.mockResolvedValueOnce({
			job_id: 'abc123',
			script: 'chat_stats',
			status: 'running',
			progress: 0,
			message: '',
			result: null,
			error: null
		});
		mockWaitJob.mockImplementationOnce(
			(_id, _onProgress, _timeout, signal) =>
				new Promise((_, reject) => {
					signal?.addEventListener('abort', () => reject(new JobCancelledError('abc123')), {
						once: true
					});
				})
		);

		render(ChatStatsPanel);
		await fillForm();
		await fireEvent.click(screen.getByRole('button', { name: /run stats/i }));

		await waitFor(() => {
			expect(screen.getByTestId('cs-cancel')).toBeInTheDocument();
		});
		await fireEvent.click(screen.getByTestId('cs-cancel'));

		await waitFor(() => {
			expect(screen.getByText(/Run cancelled/)).toBeInTheDocument();
		});
		// Run settled: the cancel control is gone and no second job ran.
		expect(screen.queryByTestId('cs-cancel')).not.toBeInTheDocument();
		expect(mockCreateJob).toHaveBeenCalledTimes(1);
	});
});
