/**
 * Backend connection store (Svelte 5 runes).
 * Rust owns the lifecycle; frontend talks HTTP directly to FastAPI on 127.0.0.1.
 * See plan.md §3 + src-tauri/src/sidecar.rs.
 */
import { invoke } from '@tauri-apps/api/core';
import { listen } from '@tauri-apps/api/event';

let port = $state(0);
let token = $state('');
let status = $state<'starting' | 'ready' | 'error'>('starting');
let error = $state('');
let initPromise: Promise<void> | null = null;
let unlistenBackendReady: (() => void) | null = null;
let retryTimer: ReturnType<typeof setTimeout> | null = null;
let disposed = false;
let lifecycle = 0;

async function fetchBackend(): Promise<boolean> {
	try {
		const [p, t] = await invoke<[number, string]>('get_backend');
		if (p > 0) {
			port = p;
			token = t;
			status = 'ready';
			error = '';
			return true;
		}
	} catch (e) {
		// Not ready yet (or running in plain `vite dev` without Tauri).
		error = e instanceof Error ? e.message : String(e);
	}
	return false;
}

async function initializeBackend(runLifecycle: number): Promise<void> {
	// Browser-only `vite dev` fallback: point at a manually started backend.
	// e.g. `VITE_BACKEND_PORT=8000 VITE_BACKEND_TOKEN=devtoken bun run dev`
	const envPort = Number(import.meta.env.VITE_BACKEND_PORT ?? 0);
	const envToken = String(import.meta.env.VITE_BACKEND_TOKEN ?? '');
	if (envPort > 0 && envToken) {
		port = envPort;
		token = envToken;
		status = 'ready';
		return;
	}

	const unlisten = await listen<number>('backend-ready', async (e) => {
		if (disposed || lifecycle !== runLifecycle) return;
		port = e.payload;
		await fetchBackend();
	});
	if (disposed || lifecycle !== runLifecycle) {
		unlisten();
		return;
	}
	unlistenBackendReady = unlisten;

	const ok = await fetchBackend();
	if (!ok && !disposed && lifecycle === runLifecycle) {
		retryTimer = setTimeout(() => {
			if (!disposed && lifecycle === runLifecycle && !port) void fetchBackend();
		}, 1500);
	}
}

export const backend = {
	get port() {
		return port;
	},
	get token() {
		return token;
	},
	get ready() {
		return port > 0 && status === 'ready';
	},
	get status() {
		return status;
	},
	get error() {
		return error;
	},
	get base() {
		return `http://127.0.0.1:${port}`;
	},
	get headers(): Record<string, string> {
		return { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' };
	},
	/** Snapshot for the Diagnostics panel (token never exposed, length only). */
	debug() {
		return {
			status,
			port,
			base: port > 0 ? `http://127.0.0.1:${port}` : '(no port yet)',
			ready: port > 0 && status === 'ready',
			tokenSet: token.length > 0,
			error
		};
	},
	async init() {
		if (!initPromise) {
			disposed = false;
			const runLifecycle = ++lifecycle;
			initPromise = initializeBackend(runLifecycle);
		}
		return initPromise;
	},
	async dispose() {
		disposed = true;
		lifecycle += 1;
		if (retryTimer) clearTimeout(retryTimer);
		retryTimer = null;
		unlistenBackendReady?.();
		unlistenBackendReady = null;
		initPromise = null;
	}
};
