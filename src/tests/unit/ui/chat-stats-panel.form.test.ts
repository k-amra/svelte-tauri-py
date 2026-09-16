import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/svelte';
import { backend } from '$lib/api/backend.svelte';
import ChatStatsPanel from '$lib/components/ChatStatsPanel.svelte';
import { fillChannel, fillForm } from '../../helpers/chat-stats';

vi.mock('$lib/api/client', () => ({
	api: { createJob: vi.fn(), waitJob: vi.fn() }
}));

import { api } from '$lib/api/client';

const mockCreateJob = vi.mocked(api.createJob);
const mockWaitJob = vi.mocked(api.waitJob);

describe('ChatStatsPanel form', () => {
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

	it('renders the form with an empty channel by default', () => {
		render(ChatStatsPanel);
		expect(screen.getByPlaceholderText('e.g., demonzz1')).toHaveValue('');
		expect(screen.getByRole('button', { name: /run stats/i })).toBeInTheDocument();
	});

	it('requires a channel when the field is left empty', async () => {
		render(ChatStatsPanel);
		await fillForm();
		const input = screen.getByPlaceholderText('e.g., demonzz1');
		await fireEvent.input(input, { target: { value: '' } });
		await fireEvent.click(screen.getByRole('button', { name: /run stats/i }));

		await waitFor(() => {
			expect(screen.getByText('At least one channel is required.')).toBeInTheDocument();
		});
		expect(mockCreateJob).not.toHaveBeenCalled();
	});

	it('requires a channel before spending a job', async () => {
		render(ChatStatsPanel);
		const input = screen.getByPlaceholderText('e.g., demonzz1');
		await fireEvent.input(input, { target: { value: '   ' } });
		await fireEvent.click(screen.getByRole('button', { name: /run stats/i }));

		await waitFor(() => {
			expect(screen.getByText('At least one channel is required.')).toBeInTheDocument();
		});
		expect(mockCreateJob).not.toHaveBeenCalled();
	});

	it('requires both dates (upstream rejects open ranges)', async () => {
		render(ChatStatsPanel);
		await fillChannel();
		await fireEvent.click(screen.getByRole('button', { name: /run stats/i }));

		await waitFor(() => {
			expect(screen.getByText('Both from and to dates are required.')).toBeInTheDocument();
		});
		expect(mockCreateJob).not.toHaveBeenCalled();
	});

	it('rejects from >= to', async () => {
		render(ChatStatsPanel);
		await fillChannel();
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
		await fillForm();
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
