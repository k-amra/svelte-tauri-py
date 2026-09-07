/**
 * The ONLY place that calls fetch() to the Python backend. Use it.
 * Every route except /health requires the bearer token (see backend.headers).
 */
import { backend } from './backend.svelte';
import type { JobStatus, RunScriptResponse, ScriptMeta } from './types';

async function apiFetch(path: string, init: RequestInit = {}, skipAuth = false) {
	if (!backend.ready) throw new Error('backend not ready yet');
	const url = `${backend.base}${path}`;
	let res: Response;
	try {
		const headers = skipAuth
			? { ...(init.headers ?? {}) }
			: { ...backend.headers, ...(init.headers ?? {}) };
		res = await fetch(url, {
			...init,
			headers
		});
	} catch (e) {
		// TypeError: network-level failure (connection refused, blocked loopback,
		// proxy/AV interference, CORS preflight rejection). The URL + hint matter
		// more than the bare "Failed to fetch".
		const detail = e instanceof Error ? e.message : String(e);
		console.error(`[api] fetch failed: ${url} — ${detail}`);
		throw new Error(
			`Cannot reach backend at ${url}: ${detail}. ` +
				`Check Diagnostics below (Rust probe vs browser fetch) and whether a proxy/antivirus filters localhost.`,
			{ cause: e }
		);
	}
	if (!res.ok) {
		const text = await res.text().catch(() => '');
		console.error(`[api] ${res.status} ${path}: ${text}`);
		throw new Error(`API ${res.status} ${path}: ${text}`);
	}
	return res.json();
}

export const api = {
	health(): Promise<{ status: string }> {
		return apiFetch('/health', {}, true);
	},
	listScripts(): Promise<ScriptMeta[]> {
		return apiFetch('/api/scripts');
	},
	runScript(name: string, params: Record<string, unknown>): Promise<RunScriptResponse> {
		return apiFetch(`/api/scripts/${name}/run`, {
			method: 'POST',
			body: JSON.stringify(params)
		});
	},
	createJob(script: string, params: Record<string, unknown>): Promise<JobStatus> {
		return apiFetch('/api/jobs', {
			method: 'POST',
			body: JSON.stringify({ script, params })
		});
	},
	getJob(jobId: string): Promise<JobStatus> {
		return apiFetch(`/api/jobs/${jobId}`);
	},
	/** Poll GET /api/jobs/{id} until done/error (simple; use SSE endpoint for live logs). */
	async waitJob(jobId: string, onProgress?: (j: JobStatus) => void): Promise<JobStatus> {
		for (let i = 0; i < 150; i++) {
			const j = await api.getJob(jobId);
			onProgress?.(j);
			if (j.status === 'done' || j.status === 'error') return j;
			await new Promise((r) => setTimeout(r, 200));
		}
		throw new Error(`job ${jobId} timed out`);
	}
};
