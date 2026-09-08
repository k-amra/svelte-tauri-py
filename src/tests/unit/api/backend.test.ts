import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { mockInvoke } from '../../setup';

vi.mock('@tauri-apps/api/event', () => ({
	listen: vi.fn(async () => () => {})
}));

import { listen } from '@tauri-apps/api/event';
import { backend } from '$lib/api/backend.svelte';

const mockListen = vi.mocked(listen);

/** Find the most recent event handler registered via listen() for the event. */
function listenHandler(event: string): (e: unknown) => unknown {
	const calls = mockListen.mock.calls.filter((c) => c[0] === event);
	expect(calls.length).toBeGreaterThan(0);
	return calls[calls.length - 1][1] as unknown as (e: unknown) => unknown;
}

describe('backend store', () => {
	beforeEach(() => {
		mockInvoke.mockReset();
	});

	afterEach(async () => {
		await backend.dispose();
	});

	it('stays starting (not error) when get_backend rejects — backend may still boot', async () => {
		mockInvoke.mockRejectedValueOnce(new Error('backend not ready yet'));
		await backend.init();
		expect(backend.ready).toBe(false);
		expect(backend.status).toBe('starting');
		expect(backend.error).toContain('backend not ready yet');
	});

	it('init() becomes ready when get_backend returns port+token', async () => {
		await backend.dispose();
		mockInvoke.mockResolvedValueOnce([4321, 'tok']);
		await backend.init();
		expect(mockInvoke).toHaveBeenCalledWith('get_backend');
		expect(backend.ready).toBe(true);
		expect(backend.port).toBe(4321);
		expect(backend.status).toBe('ready');
		expect(backend.base).toBe('http://127.0.0.1:4321');
		expect(backend.headers.Authorization).toBe('Bearer tok');
		expect(mockListen).toHaveBeenCalledWith('backend-ready', expect.any(Function));
		expect(mockListen).toHaveBeenCalledWith('backend-gone', expect.any(Function));
	});

	it("backend-gone clears state and sets status 'error'", async () => {
		await backend.dispose();
		mockInvoke.mockResolvedValueOnce([4321, 'tok']);
		await backend.init();
		expect(backend.ready).toBe(true);

		const onGone = listenHandler('backend-gone');
		onGone(undefined);

		expect(backend.ready).toBe(false);
		expect(backend.port).toBe(0);
		expect(backend.status).toBe('error');
		expect(backend.error).toContain('terminated');
	});

	it('stale backend-ready events are ignored after dispose', async () => {
		await backend.dispose();
		mockInvoke.mockResolvedValueOnce([4321, 'tok']);
		await backend.init();
		const onReady = listenHandler('backend-ready');
		const portBefore = backend.port;

		await backend.dispose();
		await onReady({ payload: 9999 });

		expect(backend.port).toBe(portBefore);
	});
});
