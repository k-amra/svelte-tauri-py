<script lang="ts">
	import { api } from '$lib/api/client';
	import { backend } from '$lib/api/backend.svelte';
	import type { ChatStatsResult, ComparisonMode } from '$lib/api/chatStats';
	import { Button } from '$lib/components/ui/button/index';
	import { Input } from '$lib/components/ui/input/index';
	import { Label } from '$lib/components/ui/label/index';
	import { Card, Header, Title, Content } from '$lib/components/ui/card/index';
	import ResultSection from '$lib/components/ResultSection.svelte';
	import ToggleChip from '$lib/components/ToggleChip.svelte';
	import ResultNav, { type ResultNavSection } from '$lib/components/ResultNav.svelte';
	import OverviewResults from '$lib/components/results/OverviewResults.svelte';
	import ActivityResults from '$lib/components/results/ActivityResults.svelte';
	import WordsEmotesResults from '$lib/components/results/WordsEmotesResults.svelte';
	import LinksCommandsResults from '$lib/components/results/LinksCommandsResults.svelte';
	import UserBehaviorResults from '$lib/components/results/UserBehaviorResults.svelte';
	import AdvancedResults from '$lib/components/results/AdvancedResults.svelte';
	import {
		exportStatsJson,
		exportTopChattersCsv,
		exportAllSectionsCsv,
		copySummaryToClipboard
	} from '$lib/api/export';
	import { ChevronDown } from '@lucide/svelte';

	let channels = $state<string[]>(['demonzz1']);

	/** 'all' = pooled multi-channel run; a channel name = stats scoped to it. */
	type ChannelScope = 'all' | string;
	let channelScope = $state<ChannelScope>('all');

	const nonEmptyChannels = $derived(channels.map((c) => c.trim()).filter(Boolean));
	const effectiveChannels = $derived(
		channelScope === 'all' ? nonEmptyChannels : nonEmptyChannels.filter((c) => c === channelScope)
	);
	/** Label for export filenames / summary headers — follows the active scope. */
	const channelLabel = $derived(effectiveChannels.join('+'));

	// If the currently-scoped channel is removed from the list, snap back to 'all'.
	$effect(() => {
		if (channelScope !== 'all' && !nonEmptyChannels.includes(channelScope)) {
			channelScope = 'all';
		}
	});

	function addChannel() {
		if (channels.length >= 3) return;
		channels = [...channels, ''];
	}
	function removeChannel(i: number) {
		channels = channels.filter((_, idx) => idx !== i);
		activeChannelDropdown = -1;
	}

	// --- Channel autocomplete (GET /api/harambelogs/channels) ---------------
	let availableChannels = $state<string[]>([]);
	let channelsLoaded = $state(false);
	let channelsLoading = $state(false);
	let activeChannelDropdown = $state(-1);

	async function loadChannels() {
		if (channelsLoaded || channelsLoading) return;
		channelsLoading = true;
		try {
			availableChannels = await api.harambelogs.getChannels();
			channelsLoaded = true;
		} catch (e) {
			// Non-fatal — the user can still type a channel name by hand.
			console.warn('[chat-stats] channel list fetch failed:', e);
		} finally {
			channelsLoading = false;
		}
	}

	function channelSuggestions(query: string, currentIndex: number): string[] {
		const q = query.trim().toLowerCase();
		// Don't suggest a channel already chosen in another slot; the current
		// slot is excluded so "change this one" still shows its own value.
		const taken = new Set(
			channels
				.filter((_, idx) => idx !== currentIndex)
				.map((c) => c.trim().toLowerCase())
				.filter(Boolean)
		);
		const pool = availableChannels.filter((c) => !taken.has(c.toLowerCase()));
		const matches = q ? pool.filter((c) => c.toLowerCase().includes(q)) : pool;
		return matches.slice(0, 20);
	}

	function pickChannel(i: number, name: string) {
		channels[i] = name;
		activeChannelDropdown = -1;
	}
	let channelType = $state<'channel' | 'channelid'>('channel');
	let userFilter = $state('');
	let userFilterType = $state<'user' | 'userid'>('user');
	let fromDate = $state('');
	let toDate = $state('');
	let topN = $state(20);
	let topWordsN = $state(50);
	let topEmotesN = $state(50);
	let topPhrasesN = $state(20);
	let sessionGapMinutes = $state(15);
	let anomalySigma = $state(3.0);
	let maxRangeDays = $state(366);

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
	let includeCopyPaste = $state(true);
	let includeStaffList = $state(false);
	let includeSubscriberList = $state(false);

	// Tier 2 toggles — all default off, matching the backend defaults.
	let includeMentionGraph = $state(false);
	let includeMutualMentions = $state(false);
	let includeEmoteCentrality = $state(false);
	let includeEmoteEntropy = $state(false);
	let includeLorenz = $state(false);
	let includeBotScores = $state(false);
	let includeLengthTrend = $state(false);
	let includeCohortRetention = $state(false);
	let includeLanguageByDay = $state(false);
	let includeQuoteReplies = $state(false);

	type Preset = 'quick' | 'standard' | 'everything';

	/** Toggles only — numeric params (top_n, gaps, sigma) are untouched. */
	function applyPreset(preset: Preset) {
		const quick = preset === 'quick';
		const everything = preset === 'everything';

		includeCommands = true;
		includeLinks = true;
		includeMentions = true;
		includeDuplicates = true;
		includeSessions = true;
		includeConcentration = !quick;
		includeMessageClass = true;
		includeNewReturning = !quick;
		includeEmotePairs = !quick;
		includeEngagement = true;
		includeAnomalies = !quick;
		includeCopyPaste = !quick;
		includeStaffList = !quick;
		includeSubscriberList = !quick;
		includePhrases = everything;
		// Language needs the optional `langdetect` package on the backend, so
		// only "Everything" turns it on — Quick/Standard leave it off.
		includeLanguage = everything;

		includeMentionGraph = everything;
		includeMutualMentions = everything;
		includeEmoteCentrality = everything;
		includeEmoteEntropy = everything;
		includeLorenz = everything;
		includeBotScores = everything;
		includeLengthTrend = everything;
		includeCohortRetention = everything;
		// Must mirror includeLanguage: the checkbox is disabled when language is off.
		includeLanguageByDay = everything;
		includeQuoteReplies = everything;
	}

	let forceRefresh = $state(false);
	let comparePrevious = $state(false);
	let comparisonMode = $state<ComparisonMode>('previous_period');
	let compareFromDate = $state('');
	let compareToDate = $state('');
	let loading = $state(false);
	let error = $state('');
	let jobProgress = $state<number | null>(null);
	let jobMessage = $state('');
	let stats = $state<ChatStatsResult | null>(null);
	let exportOpen = $state(false);
	let copiedSummary = $state(false);

	/** Post-run view tab: 'pooled' or a channel name from stats.per_channel. */
	let activeChannelTab = $state<string>('pooled');

	const displayStats = $derived.by(() => {
		if (!stats) return null;
		if (activeChannelTab === 'pooled') return stats;
		return stats.per_channel.find((c) => c.channel === activeChannelTab) || stats;
	});

	/** Label for export filenames / summary headers — follows the viewed tab. */
	const viewChannelLabel = $derived(
		activeChannelTab === 'pooled' ? channelLabel : activeChannelTab
	);

	// Reset to the pooled view whenever a new result arrives.
	$effect(() => {
		if (stats) {
			activeChannelTab = 'pooled';
		}
	});

	async function handleCopySummary() {
		const s = displayStats ?? stats;
		if (!s) return;
		await copySummaryToClipboard(
			s,
			viewChannelLabel,
			toRFC3339(fromDate) ?? '',
			toRFC3339(toDate) ?? ''
		);
		copiedSummary = true;
		setTimeout(() => (copiedSummary = false), 1500);
	}

	/** Snapshot the current result for export handlers (TS can't narrow
	 * `$state` inside closures even under an enclosing `{#if stats}`). */
	function withStats(fn: (s: ChatStatsResult) => void) {
		const s = displayStats ?? stats;
		if (s) fn(s);
	}

	/** Drill into a top chatter: scope the next run to that user. */
	function drillUser(username: string) {
		userFilter = username;
		userFilterType = 'user';
		void runStats();
	}

	/** Switch the stat scope and re-run so every number honors it. */
	function setScope(scope: ChannelScope) {
		if (scope === channelScope) return;
		channelScope = scope;
		void runStats();
	}

	function drillChannel(channel: string) {
		// The backend already returned full isolated stats per channel in
		// `stats.per_channel`; re-running the job for a channel we already
		// have in memory is pure waste. Only fall through to a fresh run
		// when the channel wasn't part of the original pooled request.
		if (stats?.per_channel.some((c) => c.channel === channel)) {
			activeChannelTab = channel;
			return;
		}
		setScope(channel);
	}

	// Close the export dropdown on any outside click while it is open.
	$effect(() => {
		if (!exportOpen) return;
		const close = () => (exportOpen = false);
		// Defer so the click that opened the menu doesn't immediately close it.
		const t = setTimeout(() => window.addEventListener('click', close), 0);
		return () => {
			clearTimeout(t);
			window.removeEventListener('click', close);
		};
	});

	// When the mode stops being 'custom', clear the custom date fields so the
	// next run doesn't accidentally send stale values.
	$effect(() => {
		if (comparisonMode !== 'custom') {
			compareFromDate = '';
			compareToDate = '';
		}
	});

	/** Local naive datetime-local input value for a Date (no timezone suffix). */
	function toLocalInputValue(d: Date): string {
		const pad = (n: number) => String(n).padStart(2, '0');
		return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
	}

	function setRange(days: number) {
		// Truncate "to" to the top of the current hour without mutating a Date
		// (svelte/prefer-svelte-reactivity flags in-place mutation).
		const now = new Date();
		const to = new Date(now.getFullYear(), now.getMonth(), now.getDate(), now.getHours());

		if (days === 0) {
			// "All": clamp to the backend's max_range_days ceiling (3660) and let
			// the fetcher further clamp to the channel's actual logged calendar.
			maxRangeDays = 3660;
			// 3650 < 3660 leaves headroom for DST / leap-day drift so the
			// backend's span check never trips on an off-by-one.
			const from = new Date(to.getTime() - 3650 * 24 * 60 * 60 * 1000);
			fromDate = toLocalInputValue(from);
			toDate = toLocalInputValue(to);
			return;
		}

		const from = new Date(to.getTime() - days * 24 * 60 * 60 * 1000);
		fromDate = toLocalInputValue(from);
		toDate = toLocalInputValue(to);
	}

	function toRFC3339(value: string): string | undefined {
		if (!value) return undefined;
		const d = new Date(value);
		return Number.isNaN(d.getTime()) ? undefined : d.toISOString();
	}

	function validate(): string | null {
		// Normalize: Svelte can hand us strings from number inputs depending
		// on runtime coercion. Coerce once here so every downstream check is
		// against real numbers.
		const topNNum = Number(topN);
		const topWordsNum = Number(topWordsN);
		const topEmotesNum = Number(topEmotesN);
		const topPhrasesNum = Number(topPhrasesN);
		const gapNum = Number(sessionGapMinutes);
		const sigmaNum = Number(anomalySigma);
		const maxRangeNum = Number(maxRangeDays);

		if (nonEmptyChannels.length === 0) return 'At least one channel is required.';
		if (nonEmptyChannels.length > 3) return 'At most 3 channels are supported.';
		// Upstream 303-redirects unbounded log requests, so a date range is mandatory.
		if (!fromDate || !toDate) return 'Both from and to dates are required.';
		if (new Date(fromDate).getTime() >= new Date(toDate).getTime()) {
			return 'The from-date must be before the to-date.';
		}
		if (!Number.isInteger(topNNum) || topNNum < 5 || topNNum > 100) {
			return 'Top N must be an integer between 5 and 100.';
		}
		if (!Number.isInteger(topWordsNum) || topWordsNum < 10 || topWordsNum > 200) {
			return 'Top words must be an integer between 10 and 200.';
		}
		if (!Number.isInteger(topEmotesNum) || topEmotesNum < 10 || topEmotesNum > 200) {
			return 'Top emotes must be an integer between 10 and 200.';
		}
		if (!Number.isInteger(topPhrasesNum) || topPhrasesNum < 0 || topPhrasesNum > 50) {
			return 'Top phrases must be an integer between 0 and 50.';
		}
		if (!Number.isInteger(gapNum) || gapNum < 2 || gapNum > 120) {
			return 'Session gap must be an integer between 2 and 120 minutes.';
		}
		// Number.isNaN missed undefined; Number.isFinite is the strict check.
		if (!Number.isFinite(sigmaNum) || sigmaNum < 1.0 || sigmaNum > 6.0) {
			return 'Anomaly sigma must be between 1.0 and 6.0.';
		}
		if (!Number.isInteger(maxRangeNum) || maxRangeNum < 1 || maxRangeNum > 3660) {
			return 'Max range must be an integer between 1 and 3660 days.';
		}
		if (comparePrevious && comparisonMode === 'custom') {
			if (!compareFromDate || !compareToDate) {
				return 'Custom comparison requires both compare dates.';
			}
			if (new Date(compareFromDate).getTime() >= new Date(compareToDate).getTime()) {
				return 'Compare from-date must be before the compare to-date.';
			}
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
				channels: effectiveChannels,
				// Keep `channel` for legacy readers; only meaningful for single-channel runs.
				channel: effectiveChannels.length === 1 ? effectiveChannels[0] : undefined,
				channel_id_type: channelType,
				// `undefined` is dropped by JSON.stringify, so the backend's
				// `user=None` default kicks in for whole-channel runs.
				user: userFilter.trim() || undefined,
				user_id_type: userFilterType,
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
				include_copy_paste_chains: includeCopyPaste,
				include_staff_list: includeStaffList,
				include_subscriber_list: includeSubscriberList,
				// Tier 2 — gated so the backend skips work unless requested.
				include_mention_graph: includeMentionGraph,
				include_mutual_mentions: includeMutualMentions,
				include_emote_centrality: includeEmoteCentrality,
				include_emote_entropy: includeEmoteEntropy,
				include_lorenz: includeLorenz,
				include_bot_scores: includeBotScores,
				include_length_trend: includeLengthTrend,
				include_cohort_retention: includeCohortRetention,
				include_language_by_day: includeLanguageByDay,
				include_quote_replies: includeQuoteReplies,
				session_gap_minutes: sessionGapMinutes,
				anomaly_sigma: anomalySigma,
				force_refresh: forceRefresh,
				compare_previous: comparePrevious,
				comparison_mode: comparisonMode,
				compare_from_date:
					comparePrevious && comparisonMode === 'custom' ? toRFC3339(compareFromDate) : undefined,
				compare_to_date:
					comparePrevious && comparisonMode === 'custom' ? toRFC3339(compareToDate) : undefined,
				max_range_days: maxRangeDays
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
	const isPerUser = $derived(userFilter.trim().length > 0);

	const resultSections: ResultNavSection[] = [
		{ id: 'rs-overview', label: 'Overview' },
		{ id: 'rs-activity', label: 'Activity & Time' },
		{ id: 'rs-words', label: 'Words & Emotes' },
		{ id: 'rs-links', label: 'Links & Commands' },
		{ id: 'rs-users', label: 'User Behavior' },
		{ id: 'rs-advanced', label: 'Advanced' }
	];
</script>

<Card class="w-full max-w-4xl shadow-xl backdrop-blur-sm">
	<Header class="pt-6">
		<Title class="text-center text-2xl font-bold">Chat Statistics</Title>
		<p class="text-muted-foreground text-center text-sm">
			Polars-powered {isPerUser ? 'user' : 'channel'} analytics (UTC)
		</p>
	</Header>
	<Content class="space-y-4 p-6">
		<div>
			<Label>Channels ({channels.length}/3)</Label>
			<div class="mt-1 space-y-2">
				{#each channels as ch, i (i)}
					<div class="flex gap-2">
						<!-- Wrapper anchors the absolutely-positioned dropdown to the input. -->
						<div class="relative flex-1">
							<Input
								bind:value={channels[i]}
								placeholder="e.g., demonzz1"
								aria-label={ch.trim() ? `Channel: ${ch.trim()}` : `Channel ${i + 1}`}
								autocomplete="off"
								onfocus={() => {
									activeChannelDropdown = i;
									void loadChannels();
								}}
								onblur={() => {
									// Delay so the dropdown item's mousedown/click can land
									// before blur closes the menu.
									setTimeout(() => {
										if (activeChannelDropdown === i) activeChannelDropdown = -1;
									}, 150);
								}}
							/>

							{#if activeChannelDropdown === i}
								{@const suggestions = channelSuggestions(channels[i] ?? '', i)}
								<div
									class="bg-popover text-popover-foreground border-border absolute top-full left-0 z-30 mt-1 max-h-56 w-full overflow-auto rounded-md border shadow-md"
									role="listbox"
									tabindex="-1"
									onmousedown={(e) => e.preventDefault()}
								>
									{#if channelsLoading && !channelsLoaded}
										<p class="text-muted-foreground px-3 py-2 text-xs">Loading channels…</p>
									{:else if suggestions.length === 0}
										<p class="text-muted-foreground px-3 py-2 text-xs">
											{availableChannels.length === 0
												? 'Channel list unavailable — type a name manually.'
												: 'No matches.'}
										</p>
									{:else}
										{#each suggestions as name (name)}
											<button
												type="button"
												role="option"
												aria-selected={name === channels[i]}
												class="hover:bg-accent hover:text-accent-foreground block w-full truncate px-3 py-1.5 text-left text-xs"
												onclick={() => pickChannel(i, name)}
											>
												{name}
											</button>
										{/each}
									{/if}
								</div>
							{/if}
						</div>

						{#if channels.length > 1}
							<Button
								variant="outline"
								size="icon"
								onclick={() => removeChannel(i)}
								aria-label="Remove channel"
							>
								×
							</Button>
						{/if}
					</div>
				{/each}
				{#if channels.length < 3}
					<Button variant="outline" size="sm" onclick={addChannel}>Add channel</Button>
				{/if}
			</div>
			<p class="text-muted-foreground mt-1 text-xs">
				Up to 3 channels. Messages are pooled; per-channel cards appear below.
			</p>
		</div>

		{#if nonEmptyChannels.length > 1}
			<div>
				<Label>Stat scope</Label>
				<div class="border-border/60 mt-1 inline-flex rounded-md border p-0.5">
					<button
						type="button"
						class="rounded px-2.5 py-1 text-xs transition-colors {channelScope === 'all'
							? 'bg-primary text-primary-foreground'
							: 'text-muted-foreground hover:bg-muted'}"
						onclick={() => setScope('all')}
					>
						All (pooled)
					</button>
					{#each nonEmptyChannels as ch (ch)}
						<button
							type="button"
							class="rounded px-2.5 py-1 text-xs transition-colors {channelScope === ch
								? 'bg-primary text-primary-foreground'
								: 'text-muted-foreground hover:bg-muted'}"
							onclick={() => setScope(ch)}
						>
							{ch} only
						</button>
					{/each}
				</div>
				<p class="text-muted-foreground mt-1 text-xs">
					Pooled shows combined stats across all channels. Pick a single channel to scope every
					number on this page — top chatters, emotes, commands, links, everything.
				</p>
			</div>
		{/if}

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

		<div class="grid grid-cols-2 gap-3">
			<div>
				<Label for="cs-user-type">User Type</Label>
				<select
					id="cs-user-type"
					bind:value={userFilterType}
					class="border-input bg-background ring-offset-background focus-visible:ring-ring mt-1 flex h-9 w-full rounded-md border px-3 py-1 text-sm shadow-xs transition-colors focus-visible:ring-2 focus-visible:ring-offset-2 focus-visible:outline-none"
				>
					<option value="user">user</option>
					<option value="userid">userid</option>
				</select>
			</div>
			<div>
				<Label for="cs-user">User (optional)</Label>
				<Input
					id="cs-user"
					bind:value={userFilter}
					placeholder="blank = whole channel"
					class="mt-1"
				/>
			</div>
		</div>

		<div>
			<div class="mb-1 flex flex-wrap gap-1.5">
				{#each [{ label: '24h', days: 1 }, { label: '7d', days: 7 }, { label: '30d', days: 30 }, { label: '90d', days: 90 }, { label: '360d', days: 360 }, { label: 'All', days: 0 }] as p (p.label)}
					<Button size="sm" variant="outline" onclick={() => setRange(p.days)}>{p.label}</Button>
				{/each}
			</div>
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
			<div>
				<Label for="cs-maxrange">Max range (days)</Label>
				<Input
					id="cs-maxrange"
					type="number"
					min="1"
					max="3660"
					step="1"
					bind:value={maxRangeDays}
					class="mt-1"
					title="Hard ceiling on the requested date range; per-day result arrays grow with it."
				/>
			</div>
		</div>

		<div class="flex flex-wrap items-center gap-2">
			<span class="text-muted-foreground text-xs font-medium">Preset:</span>
			<Button size="sm" variant="outline" onclick={() => applyPreset('quick')}>Quick</Button>
			<Button size="sm" variant="outline" onclick={() => applyPreset('standard')}>Standard</Button>
			<Button size="sm" variant="outline" onclick={() => applyPreset('everything')}
				>Everything</Button
			>
		</div>

		<details class="border-border/60 group rounded-md border">
			<summary
				class="hover:bg-muted/50 flex cursor-pointer items-center justify-between rounded-md px-3 py-2 text-sm font-medium"
			>
				<span>Sections</span>
				<span class="text-muted-foreground text-xs group-open:hidden">
					{[
						includeCommands,
						includeLinks,
						includeMentions,
						includeDuplicates,
						includeSessions,
						includeConcentration,
						includeMessageClass,
						includeNewReturning,
						includeEmotePairs,
						includeEngagement,
						includeAnomalies,
						includeCopyPaste,
						includeStaffList,
						includeSubscriberList,
						includePhrases,
						includeLanguage
					].filter(Boolean).length}
					on
				</span>
			</summary>
			<div class="grid grid-cols-2 gap-1.5 p-3 pt-0 sm:grid-cols-3">
				<ToggleChip
					bind:checked={includeCommands}
					label="Commands"
					title="Messages starting with '!' — usage count and unique users per command."
				/>
				<ToggleChip
					bind:checked={includeLinks}
					label="Links"
					title="URL extraction: top domains plus a platform breakdown (Twitch clips, YouTube, Discord, X, Kick)."
				/>
				<ToggleChip
					bind:checked={includeMentions}
					label="Mentions"
					title="@username extraction: most-mentioned users and the most frequent mention pairs."
				/>
				<ToggleChip
					bind:checked={includeDuplicates}
					label="Duplicates"
					title="Identical messages posted more than once, with the most repeated texts."
				/>
				<ToggleChip
					bind:checked={includeSessions}
					label="Sessions"
					title="Per-user activity bursts: a gap of N minutes or more starts a new session."
				/>
				<ToggleChip
					bind:checked={includeConcentration}
					label="Concentration"
					title="Gini coefficient and top-10% message share — how concentrated chat is among the top chatters."
				/>
				<ToggleChip
					bind:checked={includeMessageClass}
					label="Message classes"
					title="Message shape buckets: questions, exclamations, ALL CAPS, emote-only, short and long messages."
				/>
				<ToggleChip
					bind:checked={includeNewReturning}
					label="New vs returning"
					title="Per-day counts of chatters seen for the first time in the range vs. those seen before."
				/>
				<ToggleChip
					bind:checked={includeEmotePairs}
					label="Emote pairs"
					title="Emotes co-occurring within the same message, ranked by frequency."
				/>
				<ToggleChip
					bind:checked={includeEngagement}
					label="Engagement score"
					title="Composite 0–1 score per user (messages, active days, avg length). Adds a column to top chatters."
				/>
				<ToggleChip
					bind:checked={includeAnomalies}
					label="Anomalies"
					title="5-minute windows whose message count deviates from the mean by at least N standard deviations."
				/>
				<ToggleChip
					bind:checked={includePhrases}
					label="Phrases"
					title="Most common two-word sequences (bigrams) after URL and mention stripping."
				/>
				<ToggleChip
					bind:checked={includeCopyPaste}
					label="Copy-paste chains"
					title="Same text reposted by different users within a short window (raids / copypasta)."
				/>
				<ToggleChip
					bind:checked={includeStaffList}
					label="Mods & VIPs list"
					title="Everyone with a mod or VIP badge in the range: message count + first/last seen."
				/>
				<ToggleChip
					bind:checked={includeSubscriberList}
					label="Subscribers list"
					title="Subscribers who sent at least one message in range, ranked by volume. Capped; the header shows the true count."
				/>
				<ToggleChip
					bind:checked={includeLanguage}
					label="Language (optional)"
					title="Per-language breakdown. Requires the optional langdetect package on the backend."
				/>
			</div>
		</details>

		<details class="border-border/60 group rounded-md border">
			<summary
				class="hover:bg-muted/50 flex cursor-pointer items-center justify-between rounded-md px-3 py-2 text-sm font-medium"
			>
				<span>Advanced (Tier 2)</span>
				<span class="text-muted-foreground text-xs group-open:hidden">
					{[
						includeMentionGraph,
						includeMutualMentions,
						includeEmoteCentrality,
						includeEmoteEntropy,
						includeLorenz,
						includeBotScores,
						includeLengthTrend,
						includeCohortRetention,
						includeQuoteReplies,
						includeLanguage && includeLanguageByDay
					].filter(Boolean).length}
					on
				</span>
			</summary>
			<div class="grid grid-cols-2 gap-1.5 p-3 pt-0 sm:grid-cols-3">
				<ToggleChip
					bind:checked={includeMentionGraph}
					label="Mention graph"
					title="In/out degree per user from @mentions — who mentions, and who gets mentioned."
				/>
				<ToggleChip
					bind:checked={includeMutualMentions}
					label="Mutual mentions"
					title="Pairs of users who mention each other (both directions)."
				/>
				<ToggleChip
					bind:checked={includeEmoteCentrality}
					label="Emote centrality"
					title="Emotes ranked by how many distinct other emotes they co-occur with — the 'connector' emotes."
				/>
				<ToggleChip
					bind:checked={includeEmoteEntropy}
					label="Emote entropy"
					title="Shannon entropy (bits) of the emote frequency distribution. 0 = one emote dominates."
				/>
				<ToggleChip
					bind:checked={includeLorenz}
					label="Lorenz curve"
					title="Fixed points on the Lorenz curve: message share held by the top 1 / 5 / 10 / 25 / 50%."
				/>
				<ToggleChip
					bind:checked={includeBotScores}
					label="Bot likelihood"
					title="Heuristic 0–1 score from regular intervals, low text diversity, and command spam."
				/>
				<ToggleChip
					bind:checked={includeLengthTrend}
					label="Length trend"
					title="OLS slope of daily average message length (chars/day). Positive = messages getting longer."
				/>
				<ToggleChip
					bind:checked={includeCohortRetention}
					label="Cohort retention"
					title="Weekly signup cohorts × trailing retention over up to 8 weeks."
				/>
				<ToggleChip
					bind:checked={includeQuoteReplies}
					label="Quote replies"
					title="Inferred A→B replies: A mentions @B within 5 minutes of B's last message."
				/>
				<ToggleChip
					bind:checked={includeLanguageByDay}
					label="Language by day"
					title="Top language per calendar day. Also requires 'Language (optional)' to be enabled."
					disabled={!includeLanguage}
				/>
			</div>
		</details>

		<div
			class="bg-card/95 sticky bottom-0 z-10 -mx-6 mt-2 space-y-2 border-t px-6 pt-3 pb-1 backdrop-blur"
		>
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

			<label class="flex cursor-pointer items-center gap-2 text-sm">
				<input
					type="checkbox"
					bind:checked={forceRefresh}
					class="accent-primary h-4 w-4 rounded border-gray-300"
				/>
				<span>Bypass cache (re-download)</span>
			</label>

			<div class="flex flex-wrap items-center justify-between gap-3">
				<label class="flex cursor-pointer items-center gap-2 text-sm">
					<input
						type="checkbox"
						bind:checked={comparePrevious}
						class="accent-primary h-4 w-4 rounded border-gray-300"
					/>
					<span>Compare to previous period</span>
				</label>
				{#if comparePrevious}
					<select
						bind:value={comparisonMode}
						class="border-input bg-background ring-offset-background focus-visible:ring-ring flex h-8 rounded-md border px-2 text-xs shadow-xs transition-colors focus-visible:ring-2 focus-visible:ring-offset-2 focus-visible:outline-none"
					>
						<option value="previous_period">Same-length window</option>
						<option value="previous_week">Previous week</option>
						<option value="previous_month">Previous 30 days</option>
						<option value="previous_year">Previous year</option>
						<option value="custom">Custom range</option>
					</select>
				{/if}
			</div>

			{#if comparePrevious && comparisonMode === 'custom'}
				<div class="grid grid-cols-2 gap-3">
					<div>
						<Label for="cs-cmp-from" class="text-xs">Compare from</Label>
						<Input
							id="cs-cmp-from"
							type="datetime-local"
							bind:value={compareFromDate}
							class="mt-1 h-8 text-xs"
						/>
					</div>
					<div>
						<Label for="cs-cmp-to" class="text-xs">Compare to</Label>
						<Input
							id="cs-cmp-to"
							type="datetime-local"
							bind:value={compareToDate}
							class="mt-1 h-8 text-xs"
						/>
					</div>
				</div>
			{/if}

			{#if isPerUser}
				<button
					type="button"
					class="border-border/60 hover:bg-muted flex items-center justify-between gap-2 rounded-md border px-2.5 py-1.5 text-xs"
					onclick={() => (userFilter = '')}
					title="Remove the per-user filter and return to whole-channel stats"
				>
					<span>User filter: <span class="font-medium">{userFilter}</span></span>
					<span class="text-muted-foreground">×</span>
				</button>
			{/if}

			<Button onclick={runStats} disabled={loading || !backend.ready} class="w-full">
				{loading ? 'Analyzing…' : 'Run stats'}
			</Button>
		</div>

		{#if error}
			<p class="text-sm text-red-500">{error}</p>
		{/if}

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
			{#if (displayStats ?? stats).truncated}
				<p class="text-sm text-amber-500">
					Result truncated: channel exceeded the fetch cap — stats cover a partial window.
				</p>
			{/if}
			{#if (displayStats ?? stats).warnings.length > 0}
				<div class="rounded border border-amber-500/40 bg-amber-500/10 p-2">
					{#each (displayStats ?? stats).warnings as warning (warning)}
						<p class="text-sm text-amber-500">{warning}</p>
					{/each}
				</div>
			{/if}

			<div class="flex justify-end">
				<div class="relative">
					<Button
						size="sm"
						variant="outline"
						onclick={() => (exportOpen = !exportOpen)}
						aria-expanded={exportOpen}
					>
						Export
						<ChevronDown class="size-3.5" />
					</Button>
					{#if exportOpen}
						<div
							class="bg-popover text-popover-foreground border-border absolute right-0 z-20 mt-1 w-56 rounded-md border p-1 shadow-md"
						>
							<button
								type="button"
								class="hover:bg-accent hover:text-accent-foreground w-full rounded px-2 py-1.5 text-left text-xs"
								onclick={() =>
									withStats((s) => {
										exportStatsJson(
											s,
											viewChannelLabel,
											toRFC3339(fromDate) ?? '',
											toRFC3339(toDate) ?? ''
										);
										exportOpen = false;
									})}
							>
								Full stats (JSON)
							</button>
							<button
								type="button"
								class="hover:bg-accent hover:text-accent-foreground w-full rounded px-2 py-1.5 text-left text-xs"
								onclick={() =>
									withStats((s) => {
										exportTopChattersCsv(
											s,
											viewChannelLabel,
											toRFC3339(fromDate) ?? '',
											toRFC3339(toDate) ?? ''
										);
										exportOpen = false;
									})}
							>
								Top chatters (CSV)
							</button>
							<button
								type="button"
								class="hover:bg-accent hover:text-accent-foreground w-full rounded px-2 py-1.5 text-left text-xs"
								onclick={() =>
									withStats((s) => {
										exportAllSectionsCsv(
											s,
											viewChannelLabel,
											toRFC3339(fromDate) ?? '',
											toRFC3339(toDate) ?? ''
										);
										exportOpen = false;
									})}
							>
								All sections (CSV)
							</button>
							<button
								type="button"
								class="hover:bg-accent hover:text-accent-foreground w-full rounded px-2 py-1.5 text-left text-xs"
								onclick={() => {
									void handleCopySummary();
									exportOpen = false;
								}}
							>
								{copiedSummary ? 'Copied!' : 'Copy summary (Markdown)'}
							</button>
						</div>
					{/if}
				</div>
			</div>

			{#if stats && stats.per_channel.length > 0}
				<div
					class="bg-card/95 sticky top-0 z-30 -mx-6 mb-4 flex flex-wrap gap-2 border-b px-6 py-2 backdrop-blur"
				>
					<button
						type="button"
						class="rounded px-3 py-1.5 text-sm font-medium transition-colors {activeChannelTab ===
						'pooled'
							? 'bg-primary text-primary-foreground'
							: 'bg-muted hover:bg-muted/80 text-muted-foreground'}"
						onclick={() => (activeChannelTab = 'pooled')}
					>
						Pooled (All Channels)
					</button>
					{#each stats.per_channel as ch (ch.channel)}
						<button
							type="button"
							class="rounded px-3 py-1.5 text-sm font-medium transition-colors {activeChannelTab ===
							ch.channel
								? 'bg-primary text-primary-foreground'
								: 'bg-muted hover:bg-muted/80 text-muted-foreground'}"
							onclick={() => (activeChannelTab = ch.channel)}
						>
							{ch.channel}
						</button>
					{/each}
				</div>
			{/if}

			<div class="grid grid-cols-1 gap-x-6 gap-y-5 lg:grid-cols-2">
				{#if stats.per_channel.length > 0}
					<p class="text-muted-foreground text-xs lg:col-span-2">
						Scope:
						<span class="text-foreground font-medium">
							{activeChannelTab === 'pooled'
								? `all ${stats.per_channel.length} channels (pooled)`
								: activeChannelTab}
						</span>
					</p>
				{:else if nonEmptyChannels.length > 1}
					<p class="text-muted-foreground text-xs lg:col-span-2">
						Scope:
						<span class="text-foreground font-medium">
							{channelScope === 'all'
								? `all ${nonEmptyChannels.length} channels (pooled)`
								: channelScope}
						</span>
					</p>
				{/if}
				<ResultNav
					sections={resultSections}
					stickyTopClass={stats.per_channel.length > 0 ? 'top-11' : 'top-0'}
				/>

				<ResultSection id="rs-overview" title="Overview">
					<OverviewResults
						stats={displayStats ?? stats}
						{isPerUser}
						onDrillUser={drillUser}
						onDrillChannel={drillChannel}
					/>
				</ResultSection>
				<ResultSection id="rs-activity" title="Activity &amp; Time">
					<ActivityResults stats={displayStats ?? stats} {anomalySigma} />
				</ResultSection>
				<ResultSection id="rs-words" title="Words &amp; Emotes">
					<WordsEmotesResults
						stats={displayStats ?? stats}
						summaries={(displayStats ?? stats).channel_summaries}
					/>
				</ResultSection>
				<ResultSection id="rs-links" title="Links &amp; Commands">
					<LinksCommandsResults
						stats={displayStats ?? stats}
						summaries={(displayStats ?? stats).channel_summaries}
					/>
				</ResultSection>
				<ResultSection id="rs-users" title="User Behavior">
					<UserBehaviorResults stats={displayStats ?? stats} {isPerUser} />
				</ResultSection>
				<ResultSection id="rs-advanced" title="Advanced (Tier 2)" open={false}>
					<AdvancedResults stats={displayStats ?? stats} {isPerUser} />
				</ResultSection>
			</div>
		{/if}
	</Content>
</Card>
