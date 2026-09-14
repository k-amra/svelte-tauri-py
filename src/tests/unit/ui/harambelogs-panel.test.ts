import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, screen, waitFor, fireEvent, within } from '@testing-library/svelte';
import { backend } from '$lib/api/backend.svelte';
import HarambelogsPanel from '$lib/components/HarambelogsPanel.svelte';
import type { FullMessage } from '$lib/api/harambelogs';

vi.mock('$lib/api/client', () => ({
	api: { harambelogs: { search: vi.fn() } }
}));

import { api } from '$lib/api/client';

const mockSearch = vi.mocked(api.harambelogs.search);

function msg(partial: Partial<FullMessage> & { id: string }): FullMessage {
	return {
		type: 1,
		text: 'hello',
		displayName: 'alice',
		timestamp: '2024-01-15T10:00:00.000Z',
		tags: {},
		username: 'alice',
		channel: 'demonzz1',
		raw: 'hello',
		...partial
	};
}

const messages: FullMessage[] = [
	msg({ id: 'm1', displayName: 'alice', username: 'alice', text: 'hello world' }),
	msg({
		id: 'm2',
		displayName: 'bob',
		username: 'bob',
		text: 'check https://example.com/x @alice'
	}),
	msg({
		id: 'm3',
		displayName: 'carol',
		username: 'carol',
		text: '!shoutout bob',
		tags: { emotes: '25:0-4' }
	}),
	msg({
		id: 'm4',
		displayName: 'dave',
		username: 'dave',
		text: 'first hello 123',
		tags: { 'first-msg': '1', 'reply-parent-msg-id': 'abc' }
	})
];

async function runSearch() {
	render(HarambelogsPanel);
	await fireEvent.input(screen.getByLabelText('Search Query'), {
		target: { value: 'hello' }
	});
	await fireEvent.click(screen.getByRole('button', { name: /execute/i }));
	await waitFor(() => {
		expect(screen.getByText('alice')).toBeInTheDocument();
	});
}

describe('HarambelogsPanel filters', () => {
	beforeEach(async () => {
		vi.stubEnv('VITE_BACKEND_PORT', '9999');
		vi.stubEnv('VITE_BACKEND_TOKEN', 'test');
		mockSearch.mockReset();
		mockSearch.mockResolvedValue({ messages });
		await backend.dispose();
		await backend.init();
		expect(backend.ready).toBe(true);
	});

	afterEach(async () => {
		vi.unstubAllEnvs();
		await backend.dispose();
	});

	it('shows the filter panel for message results and narrows by text', async () => {
		await runSearch();
		expect(screen.getByText('Filters')).toBeInTheDocument();

		await fireEvent.input(screen.getByLabelText('Contains text'), {
			target: { value: 'hello' }
		});

		await waitFor(() => {
			expect(screen.getByText('1 active')).toBeInTheDocument();
		});
		expect(screen.getByText('dave')).toBeInTheDocument();
		expect(screen.queryByText('carol')).not.toBeInTheDocument();

		await fireEvent.click(screen.getByRole('button', { name: /clear filters/i }));
		await waitFor(() => {
			expect(screen.getByText('carol')).toBeInTheDocument();
		});
		expect(screen.queryByText('1 active')).not.toBeInTheDocument();
	});

	it('renders tag chips and filters by URL toggle with an empty-state hint', async () => {
		await runSearch();

		// Per-message tag chips explain why a message matched.
		expect(screen.getByText('URL')).toBeInTheDocument();
		expect(screen.getByText('!cmd')).toBeInTheDocument();
		expect(screen.getByText('emote')).toBeInTheDocument();

		await fireEvent.click(screen.getByLabelText('URLs only'));
		await waitFor(() => {
			expect(screen.getByText('bob')).toBeInTheDocument();
		});
		expect(screen.queryByText('carol')).not.toBeInTheDocument();

		// Narrow further until nothing matches.
		await fireEvent.input(screen.getByLabelText('Contains text'), {
			target: { value: 'zzz-no-match' }
		});
		await waitFor(() => {
			expect(screen.getByText('no messages match the current filters')).toBeInTheDocument();
		});
	});

	it('hides filters for non-message operations', async () => {
		await runSearch();
		expect(screen.getByText('Filters')).toBeInTheDocument();

		const select = screen.getByLabelText('Operation');
		await fireEvent.change(select, { target: { value: 'channels' } });
		expect(screen.queryByText('Filters')).not.toBeInTheDocument();
		// Switching operations clears the previous message set.
		expect(screen.queryByText('alice')).not.toBeInTheDocument();
	});

	it('filters by username and first-time chatters without refetching', async () => {
		await runSearch();

		await fireEvent.click(screen.getByLabelText('First-time chatters'));
		await waitFor(() => {
			expect(screen.getByText('dave')).toBeInTheDocument();
		});
		expect(screen.queryByText('bob')).not.toBeInTheDocument();
		// Single fetch for the whole interaction.
		expect(mockSearch).toHaveBeenCalledTimes(1);

		await fireEvent.input(screen.getByLabelText('From user'), {
			target: { value: 'dav' }
		});
		expect(screen.getByText('dave')).toBeInTheDocument();
		expect(screen.getByText('2 active')).toBeInTheDocument();

		const region = screen.getByText('dave').closest('div.border-b');
		expect(region).not.toBeNull();
		expect(within(region as HTMLElement).getByText('first')).toBeInTheDocument();
		expect(within(region as HTMLElement).getByText('reply')).toBeInTheDocument();
	});
});
