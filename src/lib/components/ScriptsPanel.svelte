<script lang="ts">
	import { onMount } from 'svelte';
	import { invoke } from '@tauri-apps/api/core';
	import { api } from '$lib/api/client';
	import { backend } from '$lib/api/backend.svelte';
	import { apiDebug } from '$lib/api/debug.svelte';
	import type { ScriptMeta } from '$lib/api/types';
	import { Button } from '$lib/components/ui/button/index';
	import { Input } from '$lib/components/ui/input/index';
	import { Card, Header, Title, Content } from '$lib/components/ui/card/index';

	let scripts = $state<ScriptMeta[]>([]);
	let loadError = $state('');
	let inputPath = $state('hello');
	let threshold = $state(0.5);
	let running = $state(false);
	let jobProgress = $state<number | null>(null);
	let jobMessage = $state('');
	let output = $state('');
	let probe = $state('');
	let probing = $state(false);
	let debugMode = $state(false);

	const statusText = $derived(
		backend.status === 'ready'
			? `Backend ready :${backend.port}`
			: backend.status === 'detached'
				? 'Detached mode (browser dev, no Tauri)'
				: backend.status === 'error'
					? 'Backend error — see Diagnostics'
					: 'Backend starting…'
	);
	const diag = $derived(backend.debug());
	const debugEntries = $derived(apiDebug.entries);

	async function refresh() {
		loadError = '';
		try {
			scripts = await api.listScripts();
		} catch (e) {
			loadError = e instanceof Error ? e.message : String(e);
		}
	}

	async function runSync() {
		running = true;
		jobProgress = null;
		output = '';
		try {
			const res = await api.runScript('example_task', {
				input_path: inputPath,
				threshold
			});
			output = JSON.stringify(res.result, null, 2);
		} catch (e) {
			output = `Error: ${e instanceof Error ? e.message : String(e)}`;
		} finally {
			running = false;
		}
	}

	async function runJob() {
		running = true;
		jobProgress = 0;
		output = '';
		try {
			const job = await api.createJob('example_task', {
				input_path: inputPath,
				threshold
			});
			const done = await api.waitJob(job.job_id, (j) => {
				jobProgress = j.progress;
				jobMessage = j.message;
			});
			if (done.status === 'done') output = JSON.stringify(done.result, null, 2);
			else output = `Job error: ${done.error}`;
		} catch (e) {
			output = `Error: ${e instanceof Error ? e.message : String(e)}`;
		} finally {
			running = false;
			jobProgress = null;
		}
	}

	onMount(() => {
		let pollTimer: ReturnType<typeof setInterval> | undefined;
		let timeoutTimer: ReturnType<typeof setTimeout> | undefined;
		let disposed = false;

		const initialize = async () => {
			// backend.init() is owned by App.svelte — just wait for ready.
			if (disposed) return;
			if (backend.ready) {
				await refresh();
				return;
			}

			// backend-ready may arrive after init; poll once while this component is mounted.
			pollTimer = setInterval(async () => {
				if (!disposed && backend.ready) {
					if (pollTimer) clearInterval(pollTimer);
					await refresh();
				}
			}, 500);
			timeoutTimer = setTimeout(() => {
				if (pollTimer) clearInterval(pollTimer);
			}, 15000);
		};

		void initialize();
		return () => {
			disposed = true;
			if (pollTimer) clearInterval(pollTimer);
			if (timeoutTimer) clearTimeout(timeoutTimer);
			// Do NOT call backend.dispose() here — lifecycle is owned by App.svelte.
		};
	});

	// F12 is a convenient, discoverable shortcut for the in-app diagnostics.
	// Keep this in the component so it is removed when the panel is unmounted.
	onMount(() => {
		function handleDebugShortcut(event: KeyboardEvent) {
			if (event.key !== 'F12') return;

			event.preventDefault();
			debugMode = !debugMode;
		}

		window.addEventListener('keydown', handleDebugShortcut);
		return () => window.removeEventListener('keydown', handleDebugShortcut);
	});

	/** Rust-side probe (raw TCP, no WebView): is the Python server alive? */
	async function runProbe() {
		probing = true;
		probe = '';
		try {
			const info = await invoke<{
				configured: boolean;
				port: number | null;
				diagnostics: { rust_health: string; rust_scripts: string } | null;
			}>('get_backend', { diagnostic: true });
			probe = JSON.stringify(info, null, 2);
		} catch (e) {
			probe = `probe invoke failed: ${e instanceof Error ? e.message : String(e)}`;
		} finally {
			probing = false;
		}
	}

	/** Browser-side ping (no auth): can the WebView itself reach the server? */
	async function pingHealth() {
		probing = true;
		probe = '';
		try {
			const res = await fetch(`${backend.base}/health`);
			probe = `browser fetch /health → ${res.status}: ${await res.text()}`;
		} catch (e) {
			probe = `browser fetch /health failed: ${e instanceof Error ? e.message : String(e)}`;
		} finally {
			probing = false;
		}
	}

	/** no-cors fetch: opaque response = TCP/HTTP fine, real call blocked by CORS. */
	async function probeCors() {
		probing = true;
		probe = '';
		try {
			const res = await fetch(`${backend.base}/health`, { mode: 'no-cors' });
			probe =
				`no-cors fetch /health → type: ${res.type}, status: ${res.status}. ` +
				(res.type === 'opaque'
					? 'Network path is FINE — the normal call is blocked by CORS policy (server allow_origins).'
					: 'Unexpected response type.');
		} catch (e) {
			probe = `no-cors fetch /health failed: ${e instanceof Error ? e.message : String(e)}. Network-level block (proxy/antivirus/firewall) — not CORS.`;
		} finally {
			probing = false;
		}
	}
</script>

<Card class="w-105 shadow-xl backdrop-blur-sm">
	<Header class="pt-6">
		<Title class="text-center text-2xl font-bold">Python Sidecar</Title>
		<p class="text-muted-foreground text-center text-sm">{statusText}</p>
	</Header>
	<Content class="space-y-3 p-6">
		{#if loadError}
			<p class="text-sm text-red-500">{loadError}</p>
			<Button variant="outline" onclick={refresh} class="w-full">Retry</Button>
		{:else if scripts.length === 0}
			<p class="text-muted-foreground text-sm">Loading scripts…</p>
		{:else}
			<ul class="text-sm">
				{#each scripts as s (s.name)}
					<li><strong>{s.name}</strong> — {s.description}</li>
				{/each}
			</ul>
		{/if}

		<div>
			<label for="script-input" class="text-sm font-medium">Input path</label>
			<Input id="script-input" bind:value={inputPath} class="mt-1" autocomplete="off" />
		</div>
		<div>
			<label for="script-threshold" class="text-sm font-medium">Threshold ({threshold})</label>
			<Input
				id="script-threshold"
				type="number"
				step="0.1"
				min="0"
				max="10"
				bind:value={threshold}
				class="mt-1"
			/>
		</div>

		{#if jobProgress !== null}
			<p class="text-sm">Job progress: {Math.round(jobProgress)}% {jobMessage}</p>
		{/if}

		<div class="flex space-x-4">
			<Button onclick={runJob} disabled={running || !backend.ready} class="flex-1">
				{running ? 'Running…' : 'Run as job'}
			</Button>
			<Button
				variant="outline"
				onclick={runSync}
				disabled={running || !backend.ready}
				class="flex-1"
				title="Synchronous call — the HTTP response arrives only when the script completes. Use for scripts that finish in <2s."
			>
				Run sync (short scripts only)
			</Button>
		</div>

		{#if output}
			<pre
				class="bg-muted max-h-40 overflow-auto rounded p-3 text-xs"
				data-testid="script-output">{output}</pre>
		{/if}

		<details class="rounded border p-3 text-xs" bind:open={debugMode}>
			<summary class="cursor-pointer font-medium">
				Diagnostics {debugMode ? '(Debug mode · F12 to hide)' : '(F12 to open)'}
			</summary>
			<dl class="mt-2 space-y-1">
				<div class="flex gap-2">
					<dt class="font-medium">Status:</dt>
					<dd>{diag.status}</dd>
				</div>
				<div class="flex gap-2">
					<dt class="font-medium">URL:</dt>
					<dd>{diag.base}</dd>
				</div>
				<div class="flex gap-2">
					<dt class="font-medium">Token:</dt>
					<dd>{diag.tokenSet ? 'set' : 'missing'}</dd>
				</div>
				{#if diag.error}
					<div class="flex gap-2">
						<dt class="font-medium">Init note:</dt>
						<dd>{diag.error}</dd>
					</div>
				{/if}
			</dl>
			{#if !diag.ready}
				<p class="text-muted-foreground mt-2">
					Backend never became ready: the sidecar likely died on startup. Run the bundled
					<code>$env:SIDECAR_TOKEN='test'; api-server.exe</code> in a terminal — if it prints no READY
					line, read its error (missing DLL, antivirus quarantine).
				</p>
			{/if}
			<div class="mt-2 flex flex-wrap gap-2">
				<Button size="sm" variant="outline" onclick={runProbe} disabled={probing}>
					{probing ? 'Probing…' : 'Probe via Rust'}
				</Button>
				<Button size="sm" variant="outline" onclick={pingHealth} disabled={probing || !diag.ready}>
					Ping /health via browser
				</Button>
				<Button size="sm" variant="outline" onclick={probeCors} disabled={probing || !diag.ready}>
					Test CORS (no-cors)
				</Button>
			</div>
			{#if probe}
				<pre class="bg-muted mt-2 max-h-40 overflow-auto rounded p-2">{probe}</pre>
				<p class="text-muted-foreground mt-1">
					Rust green + browser red: WebView↔localhost blocked (system proxy, antivirus loopback
					filter). no-cors "opaque" = network fine, CORS policy at fault. Both red = Python server
					down.
				</p>
			{/if}

			<div class="mt-3 border-t pt-3">
				<div class="flex items-center justify-between">
					<span class="font-medium">Network messages ({debugEntries.length})</span>
					<Button
						size="sm"
						variant="outline"
						onclick={apiDebug.clear}
						disabled={debugEntries.length === 0}
					>
						Clear
					</Button>
				</div>
				{#if debugEntries.length === 0}
					<p class="text-muted-foreground mt-2">
						Press Retry, run a script, or search logs to capture traffic.
					</p>
				{:else}
					<div
						class="bg-muted mt-2 max-h-56 space-y-2 overflow-auto rounded p-2 font-mono text-[10px]"
					>
						{#each debugEntries as entry (entry.id)}
							<div class="border-border/40 border-b pb-2 last:border-0">
								<div class="flex gap-2">
									<span
										class="font-bold"
										class:text-green-600={entry.direction === 'out'}
										class:text-blue-600={entry.direction === 'in'}
										class:text-red-600={entry.direction === 'error'}
									>
										{entry.direction === 'out'
											? '→ OUT'
											: entry.direction === 'in'
												? '← IN'
												: '× ERROR'}
									</span>
									<span>{new Date(entry.timestamp).toLocaleTimeString()}</span>
									<span>{entry.method} {entry.status ? `(${entry.status})` : ''}</span>
								</div>
								<div class="text-muted-foreground break-all">{entry.url}</div>
								{#if entry.payload}
									<div class="mt-1 max-h-20 overflow-auto break-all whitespace-pre-wrap">
										{entry.payload}
									</div>
								{/if}
							</div>
						{/each}
					</div>
				{/if}
			</div>
		</details>
	</Content>
</Card>
