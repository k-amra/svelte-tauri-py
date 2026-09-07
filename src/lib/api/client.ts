/**
 * The ONLY place that calls fetch() to the Python backend. Use it.
 * Every route except /health requires the bearer token (see backend.headers).
 */
import { backend } from './backend.svelte';
import { apiDebug } from './debug.svelte';
import type { JobStatus, RunScriptResponse, ScriptMeta } from './types';
import type {
	ChannelIdType,
	UserIdType,
	PreviousName,
	JsonLogsResponse,
	UserLogsStats,
	ChannelLogsStats
} from './harambelogs';

async function apiFetch(path: string, init: RequestInit = {}, skipAuth = false) {
	if (!backend.ready) throw new Error('backend not ready yet');
	const url = `${backend.base}${path}`;
	const method = init.method ?? 'GET';
	let res: Response;
	try {
		const headers = skipAuth
			? { ...(init.headers ?? {}) }
			: { ...backend.headers, ...(init.headers ?? {}) };

		apiDebug.add({
			direction: 'out',
			method,
			url,
			payload: typeof init.body === 'string' ? init.body : undefined
		});

		res = await fetch(url, {
			...init,
			headers
		});
	} catch (e) {
		// TypeError: network-level failure (connection refused, blocked loopback,
		// proxy/AV interference, CORS preflight rejection). The URL + hint matter
		// more than the bare "Failed to fetch".
		const detail = e instanceof Error ? e.message : String(e);
		apiDebug.add({ direction: 'error', method, url, payload: detail });
		console.error(`[api] fetch failed: ${url} — ${detail}`);
		throw new Error(
			`Cannot reach backend at ${url}: ${detail}. ` +
				`Check Diagnostics below (Rust probe vs browser fetch) and whether a proxy/antivirus filters localhost.`,
			{ cause: e }
		);
	}

	const responsePreview = await res
		.clone()
		.text()
		.then((text) => text || undefined)
		.catch(() => undefined);
	apiDebug.add({ direction: 'in', method, url, status: res.status, payload: responsePreview });

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
	},

	harambelogs: {
		getChannels: (): Promise<string[]> => apiFetch('/api/harambelogs/channels'),

		getCapabilities: (): Promise<string[]> => apiFetch('/api/harambelogs/capabilities'),

		getList: (channel?: string, channels?: string[]): Promise<any> => {
			const params = new URLSearchParams();
			if (channel) params.set('channel', channel);
			if (channels) params.set('channels', channels.join(','));
			const qs = params.toString();
			return apiFetch(`/api/harambelogs/list${qs ? '?' + qs : ''}`);
		},

		getNameHistory: (userId: string): Promise<PreviousName[]> =>
			apiFetch(`/api/harambelogs/namehistory/${encodeURIComponent(userId)}`),

		getUserStats: (
			cType: ChannelIdType,
			channel: string,
			uType: UserIdType,
			user: string,
			from?: string,
			to?: string
		): Promise<UserLogsStats> => {
			const p = new URLSearchParams();
			if (from) p.set('from', from);
			if (to) p.set('to', to);
			const qs = p.toString();
			return apiFetch(
				`/api/harambelogs/stats/user/${cType}/${encodeURIComponent(channel)}/${uType}/${encodeURIComponent(user)}${qs ? '?' + qs : ''}`
			);
		},

		getChannelStats: (
			cType: ChannelIdType,
			channel: string,
			from?: string,
			to?: string
		): Promise<ChannelLogsStats> => {
			const p = new URLSearchParams();
			if (from) p.set('from', from);
			if (to) p.set('to', to);
			const qs = p.toString();
			return apiFetch(
				`/api/harambelogs/stats/channel/${cType}/${encodeURIComponent(channel)}${qs ? '?' + qs : ''}`
			);
		},

		search: (
			cType: ChannelIdType,
			channel: string,
			uType: UserIdType,
			user: string,
			q: string,
			limit = 50,
			offset?: number,
			reverse = false
		): Promise<JsonLogsResponse> => {
			const p = new URLSearchParams({ q, limit: String(limit), reverse: String(reverse) });
			if (offset !== undefined) p.set('offset', String(offset));
			return apiFetch(
				`/api/harambelogs/search/${cType}/${encodeURIComponent(channel)}/${uType}/${encodeURIComponent(user)}?${p.toString()}`
			);
		},

		getChannelLogs: (
			cType: ChannelIdType,
			channel: string,
			from?: string,
			to?: string,
			limit = 50,
			offset?: number,
			reverse = false
		): Promise<JsonLogsResponse> => {
			const p = new URLSearchParams({ limit: String(limit), reverse: String(reverse) });
			if (from) p.set('from', from);
			if (to) p.set('to', to);
			if (offset !== undefined) p.set('offset', String(offset));
			return apiFetch(
				`/api/harambelogs/logs/channel/${cType}/${encodeURIComponent(channel)}?${p.toString()}`
			);
		},

		getUserLogs: (
			cType: ChannelIdType,
			channel: string,
			uType: UserIdType,
			user: string,
			from?: string,
			to?: string,
			limit = 50,
			offset?: number,
			reverse = false
		): Promise<JsonLogsResponse> => {
			const p = new URLSearchParams({ limit: String(limit), reverse: String(reverse) });
			if (from) p.set('from', from);
			if (to) p.set('to', to);
			if (offset !== undefined) p.set('offset', String(offset));
			return apiFetch(
				`/api/harambelogs/logs/user/${cType}/${encodeURIComponent(channel)}/${uType}/${encodeURIComponent(user)}?${p.toString()}`
			);
		},

		getChannelLogsByDate: (
			cType: ChannelIdType,
			channel: string,
			year: string,
			month: string,
			day: string,
			limit = 50,
			offset?: number,
			reverse = false
		): Promise<JsonLogsResponse> => {
			const p = new URLSearchParams({ limit: String(limit), reverse: String(reverse) });
			if (offset !== undefined) p.set('offset', String(offset));
			return apiFetch(
				`/api/harambelogs/logs/channel/${cType}/${encodeURIComponent(channel)}/${year}/${month}/${day}?${p.toString()}`
			);
		},

		getUserLogsByMonth: (
			cType: ChannelIdType,
			channel: string,
			uType: UserIdType,
			user: string,
			year: string,
			month: string,
			limit = 50,
			offset?: number,
			reverse = false
		): Promise<JsonLogsResponse> => {
			const p = new URLSearchParams({ limit: String(limit), reverse: String(reverse) });
			if (offset !== undefined) p.set('offset', String(offset));
			return apiFetch(
				`/api/harambelogs/logs/user/${cType}/${encodeURIComponent(channel)}/${uType}/${encodeURIComponent(user)}/${year}/${month}?${p.toString()}`
			);
		},

		getChannelRandom: (
			cType: ChannelIdType,
			channel: string,
			limit = 1
		): Promise<JsonLogsResponse> =>
			apiFetch(
				`/api/harambelogs/random/channel/${cType}/${encodeURIComponent(channel)}?limit=${limit}`
			),

		getUserRandom: (
			cType: ChannelIdType,
			channel: string,
			uType: UserIdType,
			user: string,
			limit = 1
		): Promise<JsonLogsResponse> =>
			apiFetch(
				`/api/harambelogs/random/user/${cType}/${encodeURIComponent(channel)}/${uType}/${encodeURIComponent(user)}?limit=${limit}`
			),

		optout: (): Promise<{ message: string }> =>
			apiFetch('/api/harambelogs/optout', { method: 'POST' })
	}
};
