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

vi.mock('$lib/api/external', () => ({
	openExternal: vi.fn()
}));

import { openExternal } from '$lib/api/external';

const mockOpenExternal = vi.mocked(openExternal);

describe('ChatStatsPanel dialog', () => {
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

	it('top links preview opens a dialog with the full list', async () => {
		// jsdom has no top layer (`showModal`/`close` are missing): stub both
		// so the $effect sync passes, mirroring the browser by reflecting
		// the `open` attribute.
		const proto = HTMLDialogElement.prototype as unknown as Record<string, unknown>;
		if (typeof proto.showModal !== 'function') {
			proto.showModal = function (this: HTMLDialogElement) {
				this.setAttribute('open', '');
			};
		}
		if (typeof proto.close !== 'function') {
			proto.close = function (this: HTMLDialogElement) {
				this.removeAttribute('open');
			};
		}
		const showModalSpy = vi
			.spyOn(HTMLDialogElement.prototype, 'showModal')
			.mockImplementation(function (this: HTMLDialogElement) {
				this.setAttribute('open', '');
			});
		vi.spyOn(HTMLDialogElement.prototype, 'close').mockImplementation(function (
			this: HTMLDialogElement
		) {
			this.removeAttribute('open');
		});

		const urls = Array.from({ length: 12 }, (_, i) => ({
			url: `https://example.com/${String(i).padStart(2, '0')}`,
			count: 12 - i
		}));
		const pooled = {
			...fakeStats,
			top_urls: urls.slice(0, 10),
			all_urls: urls,
			unique_url_count: 12,
			messages_with_links: 12
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
			expect(screen.getByText('Top links (by paste count)')).toBeInTheDocument();
		});
		expect(screen.getByRole('button', { name: 'https://example.com/00' })).toBeInTheDocument();
		expect(screen.getByRole('button', { name: 'https://example.com/09' })).toBeInTheDocument();
		expect(
			screen.queryByRole('button', { name: 'https://example.com/10' })
		).not.toBeInTheDocument();

		await fireEvent.click(screen.getByRole('button', { name: 'Show all 12 links' }));
		expect(showModalSpy).toHaveBeenCalled();
		const dialog = document.querySelector('dialog');
		expect(dialog).toHaveAttribute('open');
		expect(screen.getByRole('heading', { name: 'All links' })).toBeInTheDocument();
		expect(screen.getByText('12 unique · ranked by paste count')).toBeInTheDocument();
		expect(screen.getByRole('button', { name: 'https://example.com/10' })).toBeInTheDocument();
		expect(screen.getByRole('button', { name: 'https://example.com/11' })).toBeInTheDocument();

		// URL buttons inside the dialog route through the external opener.
		await fireEvent.click(screen.getByRole('button', { name: 'https://example.com/10' }));
		expect(mockOpenExternal).toHaveBeenCalledWith('https://example.com/10');

		// ✕ button closes (header comes before the footer "Close" in DOM order).
		const closeButtons = screen.getAllByRole('button', { name: 'Close' });
		expect(closeButtons).toHaveLength(2);
		await fireEvent.click(closeButtons[0]);
		expect(dialog).not.toHaveAttribute('open');

		// Backdrop click closes (target is the <dialog> itself).
		await fireEvent.click(screen.getByRole('button', { name: 'Show all 12 links' }));
		expect(dialog).toHaveAttribute('open');
		await fireEvent.click(dialog!);
		expect(dialog).not.toHaveAttribute('open');

		// Esc (cancel event) closes.
		await fireEvent.click(screen.getByRole('button', { name: 'Show all 12 links' }));
		expect(dialog).toHaveAttribute('open');
		await fireEvent(dialog!, new Event('cancel', { cancelable: true }));
		expect(dialog).not.toHaveAttribute('open');
	});
});
