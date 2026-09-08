import { describe, it, expect, beforeEach, vi } from 'vitest';
import { mockInvoke } from '../../setup';

// Mock the backend store
vi.mock('$lib/api/backend.svelte', () => ({
	backend: {
		ready: true,
		base: 'http://127.0.0.1:9999',
		headers: { Authorization: 'Bearer test', 'Content-Type': 'application/json' }
	}
}));

// Mock the debug store
vi.mock('$lib/api/debug.svelte', () => ({
	apiDebug: { add: vi.fn() }
}));

describe('api client', () => {
	beforeEach(() => {
		mockInvoke.mockReset();
		vi.restoreAllMocks();
	});

	it('health() calls /health without auth header', async () => {
		const fetchSpy = vi
			.spyOn(globalThis, 'fetch')
			.mockResolvedValueOnce(new Response(JSON.stringify({ status: 'ok' }), { status: 200 }));
		const { api } = await import('$lib/api/client');
		const res = await api.health();
		expect(res.status).toBe('ok');
		expect(fetchSpy).toHaveBeenCalledWith(
			'http://127.0.0.1:9999/health',
			expect.objectContaining({
				headers: expect.not.objectContaining({ Authorization: expect.anything() })
			})
		);
	});

	it('listScripts() includes auth header', async () => {
		const fetchSpy = vi
			.spyOn(globalThis, 'fetch')
			.mockResolvedValueOnce(new Response(JSON.stringify([]), { status: 200 }));
		const { api } = await import('$lib/api/client');
		await api.listScripts();
		expect(fetchSpy).toHaveBeenCalledWith(
			'http://127.0.0.1:9999/api/scripts',
			expect.objectContaining({
				headers: expect.objectContaining({ Authorization: 'Bearer test' })
			})
		);
	});

	it('throws descriptive error on network failure', async () => {
		vi.spyOn(globalThis, 'fetch').mockRejectedValueOnce(new TypeError('Failed to fetch'));
		const { api } = await import('$lib/api/client');
		await expect(api.health()).rejects.toThrow(/Cannot reach backend/);
	});
});
