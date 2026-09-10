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
	let topWordsN = $state(50);
	let topEmotesN = $state(50);
	let topPhrasesN = $state(20);
	let sessionGapMinutes = $state(15);
	let anomalySigma = $state(3.0);

	let includeCommands = $state(true);
	let includeLinks = $state(true);
	let includeMentions = $state(true);
	let includeDuplicates = $state(true);
	let includePhrases = $state(false);
	let includeSessions = $state(true);
	let includeConcentration = $state(true);
	let includeMessageClass = $state(true);
	let includeNewReturning = $state(true);
	let includeEmotePairs = $state(true);
	let includeEngagement = $state(true);
	let includeAnomalies = $state(true);
	let includeLanguage = $state(false);

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
		if (!Number.isInteger(topWordsN) || topWordsN < 10 || topWordsN > 200) {
			return 'Top words must be an integer between 10 and 200.';
		}
		if (!Number.isInteger(topEmotesN) || topEmotesN < 10 || topEmotesN > 200) {
			return 'Top emotes must be an integer between 10 and 200.';
		}
		if (!Number.isInteger(topPhrasesN) || topPhrasesN < 0 || topPhrasesN > 50) {
			return 'Top phrases must be an integer between 0 and 50.';
		}
		if (!Number.isInteger(sessionGapMinutes) || sessionGapMinutes < 2 || sessionGapMinutes > 120) {
			return 'Session gap must be an integer between 2 and 120 minutes.';
		}
		if (Number.isNaN(anomalySigma) || anomalySigma < 1.0 || anomalySigma > 6.0) {
			return 'Anomaly sigma must be between 1.0 and 6.0.';
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
				top_words_n: topWordsN,
				top_emotes_n: topEmotesN,
				top_phrases_n: topPhrasesN,
				include_commands: includeCommands,
				include_links: includeLinks,
				include_mentions: includeMentions,
				include_duplicates: includeDuplicates,
				include_phrases: includePhrases,
				include_sessions: includeSessions,
				include_concentration: includeConcentration,
				include_message_class: includeMessageClass,
				include_new_returning: includeNewReturning,
				include_emote_pairs: includeEmotePairs,
				include_engagement: includeEngagement,
				include_anomalies: includeAnomalies,
				include_language: includeLanguage,
				session_gap_minutes: sessionGapMinutes,
				anomaly_sigma: anomalySigma,
				force_refresh: forceRefresh,
				max_range_days: 366
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

	/** Plain-language phase for the raw backend progress message.
	 * Backend strings like "fetched X messages (page Y)" describe raw fetch
	 * counters, so translate them into what the job is actually doing. */
	function describePhase(message: string): string {
		const msg = message.trim();
		if (!msg) return 'Starting…';
		if (msg.startsWith('cache hit')) return 'Loading from local cache…';
		if (msg.startsWith('updating cache since'))
			return 'Updating cache — downloading only new messages…';
		if (msg.includes('fetching emotes')) return 'Loading emote catalog…';
		if (msg.includes('merging with cache')) return 'Merging new messages with local cache…';
		if (msg.includes('building dataframe') || msg.includes('computing stats')) {
			return 'Computing statistics…';
		}
		if (msg.includes('connecting')) return 'Connecting to log server…';
		if (msg.startsWith('done')) return 'Done';
		if (msg.includes('downloading')) return 'Downloading chat logs…';
		if (msg.includes('fetch')) return 'Downloading chat logs…';
		return msg;
	}

	const phaseLabel = $derived(describePhase(jobMessage));

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
	const maxEmotePair = $derived(
		stats && stats.top_emote_pairs.length > 0
			? Math.max(...stats.top_emote_pairs.map((p) => p.count))
			: 1
	);
	const maxCommand = $derived(
		stats && stats.top_commands.length > 0 ? Math.max(...stats.top_commands.map((c) => c.count)) : 1
	);
	const maxDomain = $derived(
		stats && stats.top_domains.length > 0 ? Math.max(...stats.top_domains.map((d) => d.count)) : 1
	);
	const maxMention = $derived(
		stats && stats.top_mentions.length > 0 ? Math.max(...stats.top_mentions.map((m) => m.count)) : 1
	);
	const maxRepeated = $derived(
		stats && stats.top_repeated_messages.length > 0
			? Math.max(...stats.top_repeated_messages.map((r) => r.count))
			: 1
	);
	const maxPhrase = $derived(
		stats && stats.top_phrases.length > 0 ? Math.max(...stats.top_phrases.map((p) => p.count)) : 1
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

		<div>
			<div class="grid grid-cols-2 gap-3">
				<div>
					<Label for="cs-from">From</Label>
					<Input id="cs-from" type="datetime-local" bind:value={fromDate} class="mt-1" />
				</div>
				<div>
					<Label for="cs-to">To</Label>
					<Input
						id="cs-to"
						type="datetime-local"
						bind:value={toDate}
						class="mt-1"
						title="Exclusive: messages at exactly this timestamp are not counted."
					/>
				</div>
			</div>
			<p class="text-muted-foreground mt-1 text-xs">
				“To” is exclusive: messages at exactly that timestamp are not included. To include all of
				Jan 31, set “To” to Feb 1 00:00.
			</p>
		</div>

		<div class="grid grid-cols-2 gap-3">
			<div>
				<Label for="cs-topn">Top chatters ({topN})</Label>
				<Input
					id="cs-topn"
					type="number"
					min="5"
					max="100"
					step="1"
					bind:value={topN}
					class="mt-1"
				/>
			</div>
			<div>
				<Label for="cs-topwords">Top words ({topWordsN})</Label>
				<Input
					id="cs-topwords"
					type="number"
					min="10"
					max="200"
					step="1"
					bind:value={topWordsN}
					class="mt-1"
				/>
			</div>
			<div>
				<Label for="cs-topemotes">Top emotes ({topEmotesN})</Label>
				<Input
					id="cs-topemotes"
					type="number"
					min="10"
					max="200"
					step="1"
					bind:value={topEmotesN}
					class="mt-1"
				/>
			</div>
			<div>
				<Label for="cs-topphrases">Top phrases ({topPhrasesN})</Label>
				<Input
					id="cs-topphrases"
					type="number"
					min="0"
					max="50"
					step="1"
					bind:value={topPhrasesN}
					class="mt-1"
				/>
			</div>
			<div>
				<Label for="cs-gap">Session gap (min)</Label>
				<Input
					id="cs-gap"
					type="number"
					min="2"
					max="120"
					step="1"
					bind:value={sessionGapMinutes}
					class="mt-1"
				/>
			</div>
			<div>
				<Label for="cs-sigma">Anomaly sigma</Label>
				<Input
					id="cs-sigma"
					type="number"
					min="1"
					max="6"
					step="0.5"
					bind:value={anomalySigma}
					class="mt-1"
				/>
			</div>
		</div>

		<fieldset class="grid grid-cols-2 gap-x-3 gap-y-1 text-sm">
			<legend class="mb-1 text-sm font-medium">Sections</legend>
			<label class="flex items-center gap-2"
				><input
					type="checkbox"
					bind:checked={includeCommands}
					class="accent-primary h-4 w-4"
				/><span>Commands</span></label
			>
			<label class="flex items-center gap-2"
				><input type="checkbox" bind:checked={includeLinks} class="accent-primary h-4 w-4" /><span
					>Links</span
				></label
			>
			<label class="flex items-center gap-2"
				><input
					type="checkbox"
					bind:checked={includeMentions}
					class="accent-primary h-4 w-4"
				/><span>Mentions</span></label
			>
			<label class="flex items-center gap-2"
				><input
					type="checkbox"
					bind:checked={includeDuplicates}
					class="accent-primary h-4 w-4"
				/><span>Duplicates</span></label
			>
			<label class="flex items-center gap-2"
				><input
					type="checkbox"
					bind:checked={includeSessions}
					class="accent-primary h-4 w-4"
				/><span>Sessions</span></label
			>
			<label class="flex items-center gap-2"
				><input
					type="checkbox"
					bind:checked={includeConcentration}
					class="accent-primary h-4 w-4"
				/><span>Concentration</span></label
			>
			<label class="flex items-center gap-2"
				><input
					type="checkbox"
					bind:checked={includeMessageClass}
					class="accent-primary h-4 w-4"
				/><span>Message classes</span></label
			>
			<label class="flex items-center gap-2"
				><input
					type="checkbox"
					bind:checked={includeNewReturning}
					class="accent-primary h-4 w-4"
				/><span>New vs returning</span></label
			>
			<label class="flex items-center gap-2"
				><input
					type="checkbox"
					bind:checked={includeEmotePairs}
					class="accent-primary h-4 w-4"
				/><span>Emote pairs</span></label
			>
			<label class="flex items-center gap-2"
				><input
					type="checkbox"
					bind:checked={includeEngagement}
					class="accent-primary h-4 w-4"
				/><span>Engagement score</span></label
			>
			<label class="flex items-center gap-2"
				><input
					type="checkbox"
					bind:checked={includeAnomalies}
					class="accent-primary h-4 w-4"
				/><span>Anomalies</span></label
			>
			<label class="flex items-center gap-2"
				><input type="checkbox" bind:checked={includePhrases} class="accent-primary h-4 w-4" /><span
					>Phrases</span
				></label
			>
			<label
				class="flex items-center gap-2"
				title="Requires the optional langdetect package on the backend"
			>
				<input type="checkbox" bind:checked={includeLanguage} class="accent-primary h-4 w-4" /><span
					>Language (optional)</span
				>
			</label>
		</fieldset>

		{#if jobProgress !== null}
			<div>
				<div class="bg-muted h-2 overflow-hidden rounded">
					<div
						class="h-full bg-teal-500 transition-all"
						style="width: {Math.round(jobProgress)}%"
					></div>
				</div>
				<p class="mt-1 text-xs font-medium" data-testid="cs-phase">
					{phaseLabel}
					{Math.round(jobProgress)}%
				</p>
				{#if jobMessage}
					<p class="text-muted-foreground text-xs" data-testid="cs-phase-detail">{jobMessage}</p>
				{/if}
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
						? ` (downloaded ${new Date(stats.cached_at).toLocaleString()})`
						: ''} — tick "Bypass cache" to re-download.
				</p>
			{:else}
				<p class="text-muted-foreground text-sm" data-testid="cs-fresh">
					Freshly downloaded — next run will reuse the local cache.
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
				<div class="bg-muted rounded p-2">
					<div class="text-xl font-bold">
						{stats.median_message_length != null ? stats.median_message_length.toFixed(1) : '—'}
					</div>
					<div class="text-muted-foreground text-xs">median length</div>
				</div>
				<div class="bg-muted rounded p-2">
					<div class="text-xl font-bold">
						{stats.avg_words_per_message != null ? stats.avg_words_per_message.toFixed(1) : '—'}
					</div>
					<div class="text-muted-foreground text-xs">avg words / msg</div>
				</div>
			</div>

			{#if stats.activity_per_day_stats.avg_active_chatters != null || stats.chatter_message_quantiles.p50 != null}
				<div class="text-muted-foreground grid grid-cols-2 gap-2 text-xs">
					{#if stats.activity_per_day_stats.avg_active_chatters != null}
						<span>
							Avg active/day: {stats.activity_per_day_stats.avg_active_chatters.toFixed(1)}
							{#if stats.activity_per_day_stats.peak_active_chatters != null}
								(peak {stats.activity_per_day_stats.peak_active_chatters})
							{/if}
						</span>
					{/if}
					{#if stats.chatter_message_quantiles.p50 != null}
						<span>
							Msgs/user p50 {stats.chatter_message_quantiles.p50}, p90 {stats
								.chatter_message_quantiles.p90}
						</span>
					{/if}
				</div>
			{/if}

			<div>
				<p class="mb-1 text-sm font-medium">Top chatters</p>
				<div class="space-y-1">
					{#each stats.top_chatters as t (t.user_id)}
						<div class="flex items-center gap-2 text-xs">
							<span
								class="w-24 truncate"
								title={t.engagement_score != null
									? `engagement ${t.engagement_score} · ${t.activeDays}d active`
									: `${t.activeDays}d active`}>{t.username}</span
							>
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

			{#if stats.top_peaks_5m.length > 0}
				<div>
					<p class="mb-1 text-sm font-medium">Peak 5-minute windows</p>
					<ul class="text-xs">
						{#each stats.top_peaks_5m as peak (peak.window_start)}
							<li>{new Date(peak.window_start).toLocaleString()} — {peak.message_count} msgs</li>
						{/each}
					</ul>
				</div>
			{/if}

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

			{#if stats.top_emote_pairs.length > 0}
				<div>
					<p class="mb-1 text-sm font-medium">Top emote pairs</p>
					<div class="space-y-1">
						{#each stats.top_emote_pairs as p (`${p.emote1}+${p.emote2}`)}
							<div class="flex items-center gap-2 text-xs">
								<span class="w-24 truncate">{p.emote1} + {p.emote2}</span>
								<div class="bg-muted h-3 flex-1 overflow-hidden rounded">
									<div
										class="h-full bg-purple-500"
										style="width: {(p.count / maxEmotePair) * 100}%"
									></div>
								</div>
								<span class="w-12 text-right">{p.count.toLocaleString()}</span>
							</div>
						{/each}
					</div>
				</div>
			{/if}

			{#if stats.top_commands.length > 0}
				<div>
					<p class="mb-1 text-sm font-medium">Top commands ({stats.messages_with_commands} msgs)</p>
					<div class="space-y-1">
						{#each stats.top_commands as c (c.name)}
							<div class="flex items-center gap-2 text-xs">
								<span class="w-24 truncate">!{c.name}</span>
								<div class="bg-muted h-3 flex-1 overflow-hidden rounded">
									<div
										class="h-full bg-amber-500"
										style="width: {(c.count / maxCommand) * 100}%"
									></div>
								</div>
								<span class="w-12 text-right">{c.count.toLocaleString()}</span>
							</div>
						{/each}
					</div>
				</div>
			{/if}

			{#if stats.top_domains.length > 0}
				<div>
					<p class="mb-1 text-sm font-medium">
						Top link domains ({stats.messages_with_links} msgs)
					</p>
					<div class="space-y-1">
						{#each stats.top_domains as d (d.domain)}
							<div class="flex items-center gap-2 text-xs">
								<span class="w-24 truncate">{d.domain}</span>
								<div class="bg-muted h-3 flex-1 overflow-hidden rounded">
									<div
										class="h-full bg-sky-500"
										style="width: {(d.count / maxDomain) * 100}%"
									></div>
								</div>
								<span class="w-12 text-right">{d.count.toLocaleString()}</span>
							</div>
						{/each}
					</div>
					<p class="text-muted-foreground mt-1 text-xs">
						Clips {stats.platform_links.twitch_clips} · YouTube {stats.platform_links.youtube} · Discord
						{stats.platform_links.discord} · X {stats.platform_links.x_twitter} · Kick {stats
							.platform_links.kick} · Other {stats.platform_links.other}
					</p>
				</div>
			{/if}

			{#if stats.top_mentions.length > 0}
				<div>
					<p class="mb-1 text-sm font-medium">Top mentions ({stats.messages_with_mentions} msgs)</p>
					<div class="space-y-1">
						{#each stats.top_mentions as m (m.username)}
							<div class="flex items-center gap-2 text-xs">
								<span class="w-24 truncate">@{m.username}</span>
								<div class="bg-muted h-3 flex-1 overflow-hidden rounded">
									<div
										class="h-full bg-emerald-500"
										style="width: {(m.count / maxMention) * 100}%"
									></div>
								</div>
								<span class="w-12 text-right">{m.count.toLocaleString()}</span>
							</div>
						{/each}
					</div>
					{#if stats.top_mention_pairs.length > 0}
						<ul class="text-muted-foreground mt-1 space-y-0.5 text-xs">
							{#each stats.top_mention_pairs.slice(0, 5) as pair (`${pair.from_user}-${pair.to_user}`)}
								<li>{pair.from_user} → {pair.to_user}: {pair.count}</li>
							{/each}
						</ul>
					{/if}
				</div>
			{/if}

			{#if stats.top_repeated_messages.length > 0}
				<div>
					<p class="mb-1 text-sm font-medium">
						Repeated messages ({stats.duplicate_message_count} dupes)
					</p>
					<div class="space-y-1">
						{#each stats.top_repeated_messages.slice(0, 10) as r (r.text)}
							<div class="flex items-center gap-2 text-xs">
								<span class="flex-1 truncate" title={r.text}>{r.text}</span>
								<div class="bg-muted h-3 w-24 overflow-hidden rounded">
									<div
										class="h-full bg-rose-500"
										style="width: {(r.count / maxRepeated) * 100}%"
									></div>
								</div>
								<span class="w-12 text-right">{r.count.toLocaleString()}</span>
							</div>
						{/each}
					</div>
				</div>
			{/if}

			{#if stats.roles.length > 0}
				<div>
					<p class="mb-1 text-sm font-medium">Roles</p>
					<ul class="grid grid-cols-2 gap-1 text-xs">
						{#each stats.roles as role (role.role)}
							<li class="bg-muted rounded px-2 py-1">
								{role.role}: {role.messages.toLocaleString()} msgs · {role.unique_users} users
							</li>
						{/each}
					</ul>
				</div>
			{/if}

			{#if stats.sessions.total_sessions > 0}
				<div class="text-xs">
					<p class="mb-1 text-sm font-medium">Sessions</p>
					<p class="text-muted-foreground">
						{stats.sessions.total_sessions} sessions · avg {stats.sessions.avg_messages_per_session?.toFixed(
							1
						) ?? '—'} msgs · avg {stats.sessions.avg_session_minutes?.toFixed(1) ?? '—'} min · longest
						{stats.sessions.longest_session_minutes?.toFixed(1) ?? '—'} min
					</p>
				</div>
			{/if}

			{#if stats.concentration.gini_coefficient != null}
				<div class="text-xs">
					<p class="mb-1 text-sm font-medium">Concentration</p>
					<p class="text-muted-foreground">
						Gini {stats.concentration.gini_coefficient} · top 10% share {stats.concentration
							.top_10pct_share}%
					</p>
				</div>
			{/if}

			<div class="text-xs">
				<p class="mb-1 text-sm font-medium">Message classes</p>
				<p class="text-muted-foreground">
					? {stats.message_classes.questions} · ! {stats.message_classes.exclamations} · CAPS {stats
						.message_classes.all_caps} · emote-only {stats.message_classes.emote_only} · short {stats
						.message_classes.short_messages} · long {stats.message_classes.long_messages}
				</p>
			</div>

			{#if stats.top_phrases.length > 0}
				<div>
					<p class="mb-1 text-sm font-medium">Top phrases</p>
					<div class="space-y-1">
						{#each stats.top_phrases as p (p.phrase)}
							<div class="flex items-center gap-2 text-xs">
								<span class="flex-1 truncate">{p.phrase}</span>
								<div class="bg-muted h-3 w-24 overflow-hidden rounded">
									<div
										class="h-full bg-teal-500"
										style="width: {(p.count / maxPhrase) * 100}%"
									></div>
								</div>
								<span class="w-12 text-right">{p.count.toLocaleString()}</span>
							</div>
						{/each}
					</div>
				</div>
			{/if}

			{#if stats.anomalies_5m.length > 0}
				<div>
					<p class="mb-1 text-sm font-medium">Anomalies (5m, z ≥ {anomalySigma})</p>
					<ul class="text-xs">
						{#each stats.anomalies_5m.slice(0, 10) as a (a.window_start)}
							<li>
								{new Date(a.window_start).toLocaleString()} — {a.message_count} msgs (z {a.z_score})
							</li>
						{/each}
					</ul>
				</div>
			{/if}

			{#if stats.language_breakdown.length > 0}
				<div>
					<p class="mb-1 text-sm font-medium">Language</p>
					<ul class="text-xs">
						{#each stats.language_breakdown as l (l.language)}
							<li>{l.language}: {l.percentage}%</li>
						{/each}
					</ul>
				</div>
			{/if}
		{/if}
	</Content>
</Card>
