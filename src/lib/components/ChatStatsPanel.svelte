<script lang="ts">
	import { api } from '$lib/api/client';
	import { backend } from '$lib/api/backend.svelte';
	import type { ChatStatsResult } from '$lib/api/chatStats';
	import { WEEKDAY_LABELS } from '$lib/api/chatStats';
	import { Button } from '$lib/components/ui/button/index';
	import { Input } from '$lib/components/ui/input/index';
	import { Label } from '$lib/components/ui/label/index';
	import { Card, Header, Title, Content } from '$lib/components/ui/card/index';

	let channel = $state('demonzz1');
	let channelType = $state<'channel' | 'channelid'>('channel');
	let fromDate = $state('');
	let toDate = $state('');
	let topN = $state(20);
	let forceRefresh = $state(false);
	let loading = $state(false);
	let error = $state('');
	let jobProgress = $state<number | null>(null);
	let jobMessage = $state('');
	let stats = $state<ChatStatsResult | null>(null);

	/** Same pattern as HarambelogsPanel: local naive input → UTC RFC 3339. */
	function toRFC3339(value: string): string | undefined {
		if (!value) return undefined;
		const d = new Date(value);
		return Number.isNaN(d.getTime()) ? undefined : d.toISOString();
	}

	function validate(): string | null {
		if (!channel.trim()) return 'Channel is required.';
		// Upstream 303-redirects unbounded log requests, so a date range is mandatory.
		if (!fromDate || !toDate) return 'Both from and to dates are required.';
		if (new Date(fromDate).getTime() >= new Date(toDate).getTime()) {
			return 'The from-date must be before the to-date.';
		}
		if (!Number.isInteger(topN) || topN < 5 || topN > 100) {
			return 'Top N must be an integer between 5 and 100.';
		}
		return null;
	}

	async function runStats() {
		error = '';
		stats = null;
		loading = true;
		jobProgress = 0;
		jobMessage = '';

		const validationError = validate();
		if (validationError) {
			error = validationError;
			loading = false;
			jobProgress = null;
			return;
		}

		try {
			const job = await api.createJob('chat_stats', {
				channel: channel.trim(),
				channel_id_type: channelType,
				from_date: toRFC3339(fromDate),
				to_date: toRFC3339(toDate),
				top_n: topN,
				force_refresh: forceRefresh
			});
			const done = await api.waitJob(job.job_id, (j) => {
				jobProgress = j.progress;
				jobMessage = j.message;
			});
			if (done.status === 'done') {
				stats = done.result as ChatStatsResult;
			} else {
				error = `Job error: ${done.error ?? 'unknown'}`;
			}
		} catch (e) {
			error = e instanceof Error ? e.message : String(e);
		} finally {
			loading = false;
			jobProgress = null;
		}
	}

	const maxHour = $derived(stats ? Math.max(1, ...stats.activity_by_hour) : 1);
	const maxHeat = $derived(stats ? Math.max(1, ...stats.activity_by_weekday_hour.flat()) : 1);
	const maxTop = $derived(
		stats && stats.top_chatters.length > 0
			? Math.max(...stats.top_chatters.map((t) => t.messageCount))
			: 1
	);
	const maxDay = $derived(
		stats && stats.messages_per_day.length > 0
			? Math.max(...stats.messages_per_day.map((d) => d.count))
			: 1
	);
	const maxWord = $derived(
		stats && stats.top_words.length > 0 ? Math.max(...stats.top_words.map((w) => w.count)) : 1
	);
	const maxEmote = $derived(
		stats && stats.top_emotes.length > 0 ? Math.max(...stats.top_emotes.map((e) => e.count)) : 1
	);
</script>

<Card class="w-120 shadow-xl backdrop-blur-sm">
	<Header class="pt-6">
		<Title class="text-center text-2xl font-bold">Chat Statistics</Title>
		<p class="text-muted-foreground text-center text-sm">Polars-powered channel analytics (UTC)</p>
	</Header>
	<Content class="space-y-4 p-6">
		<div class="grid grid-cols-2 gap-3">
			<div>
				<Label for="cs-channel-type">Channel Type</Label>
				<select
					id="cs-channel-type"
					bind:value={channelType}
					class="border-input bg-background ring-offset-background focus-visible:ring-ring mt-1 flex h-9 w-full rounded-md border px-3 py-1 text-sm shadow-xs transition-colors focus-visible:ring-2 focus-visible:ring-offset-2 focus-visible:outline-none"
				>
					<option value="channel">channel</option>
					<option value="channelid">channelid</option>
				</select>
			</div>
			<div>
				<Label for="cs-channel">Channel</Label>
				<Input id="cs-channel" bind:value={channel} placeholder="e.g., demonzz1" class="mt-1" />
			</div>
		</div>

		<div class="grid grid-cols-2 gap-3">
			<div>
				<Label for="cs-from">From</Label>
				<Input id="cs-from" type="datetime-local" bind:value={fromDate} class="mt-1" />
			</div>
			<div>
				<Label for="cs-to">To</Label>
				<Input id="cs-to" type="datetime-local" bind:value={toDate} class="mt-1" />
			</div>
		</div>

		<div>
			<Label for="cs-topn">Top chatters ({topN})</Label>
			<Input id="cs-topn" type="number" min="5" max="100" step="1" bind:value={topN} class="mt-1" />
		</div>

		{#if jobProgress !== null}
			<div>
				<div class="bg-muted h-2 overflow-hidden rounded">
					<div
						class="h-full bg-teal-500 transition-all"
						style="width: {Math.round(jobProgress)}%"
					></div>
				</div>
				<p class="text-muted-foreground mt-1 text-xs">
					{Math.round(jobProgress)}% {jobMessage}
				</p>
			</div>
		{/if}

		{#if error}
			<p class="text-sm text-red-500">{error}</p>
		{/if}

		<label class="flex cursor-pointer items-center gap-2 text-sm">
			<input
				type="checkbox"
				bind:checked={forceRefresh}
				class="accent-primary h-4 w-4 rounded border-gray-300"
			/>
			<span>Bypass cache (re-download)</span>
		</label>

		<Button onclick={runStats} disabled={loading || !backend.ready} class="w-full">
			{loading ? 'Analyzing…' : 'Run stats'}
		</Button>

		{#if stats}
			{#if stats.from_cache}
				<p class="text-muted-foreground text-sm">
					Loaded from local cache{stats.cached_at
						? ` (fetched ${new Date(stats.cached_at).toLocaleString()})`
						: ''} — tick "Bypass cache" to re-download.
				</p>
			{/if}
			{#if stats.truncated}
				<p class="text-sm text-amber-500">
					Result truncated: channel exceeded the fetch cap — stats cover a partial window.
				</p>
			{/if}

			<div class="grid grid-cols-2 gap-2 text-center">
				<div class="bg-muted rounded p-2">
					<div class="text-xl font-bold" data-testid="cs-total">
						{stats.total_messages.toLocaleString()}
					</div>
					<div class="text-muted-foreground text-xs">messages</div>
				</div>
				<div class="bg-muted rounded p-2">
					<div class="text-xl font-bold">{stats.unique_chatters.toLocaleString()}</div>
					<div class="text-muted-foreground text-xs">chatters</div>
				</div>
				<div class="bg-muted rounded p-2">
					<div class="text-xl font-bold">{stats.days_spanned}</div>
					<div class="text-muted-foreground text-xs">days spanned</div>
				</div>
				<div class="bg-muted rounded p-2">
					<div class="text-xl font-bold">{stats.avg_message_length.toFixed(1)}</div>
					<div class="text-muted-foreground text-xs">avg length</div>
				</div>
			</div>

			<div>
				<p class="mb-1 text-sm font-medium">Top chatters</p>
				<div class="space-y-1">
					{#each stats.top_chatters as t (t.username)}
						<div class="flex items-center gap-2 text-xs">
							<span class="w-24 truncate">{t.username}</span>
							<div class="bg-muted h-3 flex-1 overflow-hidden rounded">
								<div
									class="h-full bg-teal-500"
									style="width: {(t.messageCount / maxTop) * 100}%"
								></div>
							</div>
							<span class="w-12 text-right">{t.messageCount.toLocaleString()}</span>
						</div>
					{/each}
				</div>
			</div>

			<div>
				<p class="mb-1 text-sm font-medium">Activity by hour (UTC)</p>
				<div class="flex h-20 items-end gap-0.5">
					{#each stats.activity_by_hour as count, h (h)}
						<div
							class="flex-1 rounded-t bg-teal-500"
							style="height: {Math.max(2, (count / maxHour) * 100)}%"
							title="{h}:00 — {count}"
						></div>
					{/each}
				</div>
			</div>

			<div>
				<p class="mb-1 text-sm font-medium">Weekday × hour heatmap (UTC)</p>
				<div class="grid gap-0.5" style="grid-template-columns: auto repeat(24, minmax(0, 1fr));">
					{#each stats.activity_by_weekday_hour as row, d (WEEKDAY_LABELS[d])}
						<span class="text-muted-foreground pr-1 text-right text-[10px]"
							>{WEEKDAY_LABELS[d]}</span
						>
						{#each row as count, h (`${d}-${h}`)}
							<div
								class="aspect-square rounded-[2px] bg-teal-500"
								style="opacity: {count === 0 ? 0.08 : 0.15 + 0.85 * (count / maxHeat)}"
								title="{WEEKDAY_LABELS[d]} {h}:00 — {count}"
							></div>
						{/each}
					{/each}
				</div>
			</div>

			<div>
				<p class="mb-1 text-sm font-medium">Messages per day</p>
				<div class="bg-muted flex h-16 max-w-full items-end gap-0.5 overflow-x-auto rounded p-1">
					{#each stats.messages_per_day as day (day.date)}
						<div
							class="min-w-1.5 flex-1 rounded-t bg-teal-500"
							style="height: {Math.max(3, (day.count / maxDay) * 100)}%"
							title="{day.date} — {day.count}"
						></div>
					{/each}
				</div>
			</div>

			<div>
				<p class="mb-1 text-sm font-medium">Top words</p>
				<div class="space-y-1">
					{#each stats.top_words as w (w.word)}
						<div class="flex items-center gap-2 text-xs">
							<span class="w-24 truncate">{w.word}</span>
							<div class="bg-muted h-3 flex-1 overflow-hidden rounded">
								<div class="h-full bg-teal-500" style="width: {(w.count / maxWord) * 100}%"></div>
							</div>
							<span class="w-12 text-right">{w.count.toLocaleString()}</span>
						</div>
					{/each}
				</div>
			</div>

			{#if stats.top_emotes.length > 0}
				<div>
					<p class="mb-1 text-sm font-medium">Top emotes</p>
					<div class="space-y-1">
						{#each stats.top_emotes as e (e.name)}
							<div class="flex items-center gap-2 text-xs">
								<span class="w-24 truncate" title={e.name}>{e.name}</span>
								<div class="bg-muted h-3 flex-1 overflow-hidden rounded">
									<div
										class="h-full bg-purple-500"
										style="width: {(e.count / maxEmote) * 100}%"
									></div>
								</div>
								<span class="w-12 text-right">{e.count.toLocaleString()}</span>
							</div>
						{/each}
					</div>
				</div>
			{/if}
		{/if}
	</Content>
</Card>
