import { describe, it, expect, beforeEach, vi } from 'vitest';
import { mockInvoke } from '../../setup';
import type { JobStatus } from '$lib/api/types';

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

	function streamResponse(frames: string[]): Response {
		const enc = new TextEncoder();
		const stream = new ReadableStream<Uint8Array>({
			start(c) {
				for (const f of frames) c.enqueue(enc.encode(f));
				c.close();
			}
		});
		return new Response(stream, { status: 200 });
	}

	function jobStatus(overrides: Partial<JobStatus> = {}): JobStatus {
		return {
			job_id: 'abc123',
			script: 'chat_stats',
			status: 'running',
			progress: 0,
			message: '',
			result: null,
			error: null,
			...overrides
		};
	}

	it('waitJob() streams SSE progress until the done event', async () => {
		const done = jobStatus({ status: 'done', progress: 100, message: 'done', result: { n: 1 } });
		const fetchSpy = vi.spyOn(globalThis, 'fetch');
		fetchSpy.mockResolvedValueOnce(new Response(JSON.stringify(jobStatus()), { status: 200 }));
		fetchSpy.mockResolvedValueOnce(
			streamResponse([
				`data: ${JSON.stringify({ seq: 0, progress: 10, message: 'ten', t: 1 })}\n\n`,
				`data: ${JSON.stringify({ seq: 1, progress: 50, message: 'half', t: 2 })}\n\n`,
				`event: done\ndata: ${JSON.stringify(done)}\n\n`
			])
		);
		const { api } = await import('$lib/api/client');
		const seen: string[] = [];
		const result = await api.waitJob('abc123', (j) => seen.push(`${j.progress}:${j.message}`));
		expect(result).toEqual(done);
		expect(seen).toEqual(['0:', '10:ten', '50:half']);
		expect(fetchSpy).toHaveBeenCalledWith(
			'http://127.0.0.1:9999/api/jobs/abc123/events',
			expect.objectContaining({
				headers: expect.objectContaining({ Authorization: 'Bearer test' })
			})
		);
	});

	it('waitJob() parses CRLF-delimited SSE frames', async () => {
		const done = jobStatus({ status: 'done', progress: 100, message: 'done', result: { n: 1 } });
		const fetchSpy = vi.spyOn(globalThis, 'fetch');
		fetchSpy.mockResolvedValueOnce(new Response(JSON.stringify(jobStatus()), { status: 200 }));
		fetchSpy.mockResolvedValueOnce(
			streamResponse([
				`data: ${JSON.stringify({ seq: 0, progress: 10, message: 'ten', t: 1 })}\r\n\r\n`,
				`event: done\r\ndata: ${JSON.stringify(done)}\r\n\r\n`
			])
		);
		const { api } = await import('$lib/api/client');
		const seen: string[] = [];
		const result = await api.waitJob('abc123', (j) => seen.push(`${j.progress}:${j.message}`));
		expect(result).toEqual(done);
		expect(seen).toEqual(['0:', '10:ten']);
	});

	it('waitJob() returns the seed directly when already terminal', async () => {
		const done = jobStatus({ status: 'done', progress: 100, message: 'done' });
		const fetchSpy = vi.spyOn(globalThis, 'fetch');
		fetchSpy.mockResolvedValueOnce(new Response(JSON.stringify(done), { status: 200 }));
		const { api } = await import('$lib/api/client');
		const seen: string[] = [];
		const result = await api.waitJob('abc123', (j) => seen.push(j.status));
		expect(result).toEqual(done);
		expect(seen).toEqual(['done']);
		// Seed only — no SSE round-trip.
		expect(fetchSpy).toHaveBeenCalledTimes(1);
	});

	it('apiFetch() skips the debug preview for large bodies', async () => {
		const big = 'x'.repeat(70_000);
		const fetchSpy = vi.spyOn(globalThis, 'fetch');
		fetchSpy.mockResolvedValueOnce(
			new Response(JSON.stringify({ status: big }), {
				status: 200,
				headers: { 'content-length': String(70_010) }
			})
		);
		const { api } = await import('$lib/api/client');
		const { apiDebug } = await import('$lib/api/debug.svelte');
		const add = vi.mocked(apiDebug.add);
		add.mockClear();
		const res = await api.health();
		expect(res.status).toBe(big);
		const inbound = add.mock.calls.find((c) => c[0].direction === 'in');
		expect(inbound?.[0].payload).toBeUndefined();
	});

	it('apiFetch() still previews small bodies', async () => {
		const fetchSpy = vi.spyOn(globalThis, 'fetch');
		fetchSpy.mockResolvedValueOnce(
			new Response(JSON.stringify({ status: 'ok' }), {
				status: 200,
				headers: { 'content-length': '15' }
			})
		);
		const { api } = await import('$lib/api/client');
		const { apiDebug } = await import('$lib/api/debug.svelte');
		const add = vi.mocked(apiDebug.add);
		add.mockClear();
		await api.health();
		const inbound = add.mock.calls.find((c) => c[0].direction === 'in');
		expect(inbound?.[0].payload).toContain('ok');
	});

	it('waitJob() keeps the timeout contract on abort', async () => {
		// A stream that pends forever, errored by the abort signal —
		// emulating what a real fetch does when its signal fires mid-read.
		let errorStream: ((e: unknown) => void) | null = null;
		const hanging = new ReadableStream<Uint8Array>({
			start(c) {
				errorStream = (e: unknown) => c.error(e);
			}
		});
		const fetchSpy = vi.spyOn(globalThis, 'fetch');
		fetchSpy.mockResolvedValueOnce(new Response(JSON.stringify(jobStatus()), { status: 200 }));
		fetchSpy.mockImplementationOnce((_url, init) => {
			const signal = (init as RequestInit | undefined)?.signal as AbortSignal | undefined;
			signal?.addEventListener('abort', () =>
				errorStream?.(new DOMException('aborted', 'AbortError'))
			);
			return Promise.resolve(new Response(hanging, { status: 200 }));
		});
		const { api } = await import('$lib/api/client');
		await expect(api.waitJob('abc123', undefined, 50)).rejects.toThrow(/timed out after 50ms/);
		expect(fetchSpy).toHaveBeenCalledTimes(2);
	});
});
