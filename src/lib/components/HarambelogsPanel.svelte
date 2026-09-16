<script lang="ts">
	import { api } from '$lib/api/client';
	import { backend } from '$lib/api/backend.svelte';
	import type {
		FullMessage,
		UserLogsStats,
		ChannelLogsStats,
		PreviousName
	} from '$lib/api/harambelogs';
	import { Button } from '$lib/components/ui/button/index';
	import { Input } from '$lib/components/ui/input/index';
	import { Card, Header, Title, Content } from '$lib/components/ui/card/index';
	import { Label } from '$lib/components/ui/label/index';
	import { URL_RE } from '$lib/api/patterns';

	type Operation =
		| 'channels'
		| 'capabilities'
		| 'list'
		| 'namehistory'
		| 'stats/user'
		| 'stats/channel'
		| 'search'
		| 'logs/channel'
		| 'logs/user'
		| 'logs/channel/date'
		| 'logs/user/month'
		| 'random/channel'
		| 'random/user'
		| 'optout';

	let operation = $state<Operation>('search');
	let loading = $state(false);
	let error = $state('');
	let result = $state<string>('');
	let messages = $state<FullMessage[]>([]);
	let statsUser = $state<UserLogsStats | null>(null);
	let statsChannel = $state<ChannelLogsStats | null>(null);
	let nameHistory = $state<PreviousName[]>([]);
	let rawResult = $state<string[]>([]);

	// Common fields
	let channel = $state('demonzz1');
	let user = $state('demonzz1');
	let userId = $state('');
	let query = $state('');
	let channelType = $state<'channel' | 'channelid'>('channel');
	let userType = $state<'user' | 'userid'>('user');

	// Date range
	let fromDate = $state('');
	let toDate = $state('');

	// Pagination
	let limit = $state('50');
	let offset = $state('');
	let reverse = $state(false);

	// Date-specific
	let year = $state('');
	let month = $state('');
	let day = $state('');

	// --- Client-side filters (apply to the fetched `messages` array) -------
	/** Free-text substring (case-insensitive) matched against message text. */
	let filterText = $state('');
	let filterContainsUrl = $state(false);
	let filterContainsMention = $state(false);
	let filterContainsCommand = $state(false);
	let filterContainsEmote = $state(false);
	let filterContainsNumber = $state(false);
	let filterOnlyReplies = $state(false);
	let filterOnlyFirstMsg = $state(false);
	let filterOnlyReturning = $state(false);
	let filterMinLength = $state<number | null>(null);
	let filterMaxLength = $state<number | null>(null);
	let filterUsername = $state('');
	let filtersOpen = $state(false);

	function clearFilters() {
		filterText = '';
		filterContainsUrl = false;
		filterContainsMention = false;
		filterContainsCommand = false;
		filterContainsEmote = false;
		filterContainsNumber = false;
		filterOnlyReplies = false;
		filterOnlyFirstMsg = false;
		filterOnlyReturning = false;
		filterMinLength = null;
		filterMaxLength = null;
		filterUsername = '';
	}

	const activeFilterCount = $derived(
		[
			filterText.trim().length > 0,
			filterContainsUrl,
			filterContainsMention,
			filterContainsCommand,
			filterContainsEmote,
			filterContainsNumber,
			filterOnlyReplies,
			filterOnlyFirstMsg,
			filterOnlyReturning,
			filterMinLength != null,
			filterMaxLength != null,
			filterUsername.trim().length > 0
		].filter(Boolean).length
	);

	// --- Regexes reused across the panel -----------------------------------
	// URL_RE lives in $lib/api/patterns.ts (with sync tests) so the panel
	// and the backend analytics match on query strings.
	const MENTION_RE = /\B@[A-Za-z0-9_]+/;
	const COMMAND_RE = /^\s*![A-Za-z0-9_-]+/;

	/** Extract a message's tags as a typed-ish object for safe lookups. */
	function tagOf(msg: FullMessage, key: string): string | undefined {
		const v = msg.tags?.[key];
		return typeof v === 'string' ? v : undefined;
	}

	function hasUrl(msg: FullMessage): boolean {
		return URL_RE.test(msg.text);
	}
	function hasMention(msg: FullMessage): boolean {
		return MENTION_RE.test(msg.text);
	}
	function hasCommand(msg: FullMessage): boolean {
		return COMMAND_RE.test(msg.text);
	}
	function hasEmote(msg: FullMessage): boolean {
		const emotes = tagOf(msg, 'emotes');
		return !!emotes && emotes.length > 0;
	}
	function hasNumber(msg: FullMessage): boolean {
		return /\d/.test(msg.text);
	}
	function isReply(msg: FullMessage): boolean {
		return !!tagOf(msg, 'reply-parent-msg-id');
	}
	function isFirstMsg(msg: FullMessage): boolean {
		return tagOf(msg, 'first-msg') === '1';
	}
	function isReturningChatter(msg: FullMessage): boolean {
		return tagOf(msg, 'returning-chatter') === '1';
	}

	const filteredMessages = $derived.by(() => {
		const text = filterText.trim().toLowerCase();
		const uname = filterUsername.trim().toLowerCase();
		return messages.filter((m) => {
			if (text && !m.text.toLowerCase().includes(text)) return false;
			if (uname && !m.username.toLowerCase().includes(uname)) return false;
			if (filterContainsUrl && !hasUrl(m)) return false;
			if (filterContainsMention && !hasMention(m)) return false;
			if (filterContainsCommand && !hasCommand(m)) return false;
			if (filterContainsEmote && !hasEmote(m)) return false;
			if (filterContainsNumber && !hasNumber(m)) return false;
			if (filterOnlyReplies && !isReply(m)) return false;
			if (filterOnlyFirstMsg && !isFirstMsg(m)) return false;
			if (filterOnlyReturning && !isReturningChatter(m)) return false;
			const len = m.text.length;
			const minLen =
				typeof filterMinLength === 'number' && !Number.isNaN(filterMinLength)
					? filterMinLength
					: null;
			const maxLen =
				typeof filterMaxLength === 'number' && !Number.isNaN(filterMaxLength)
					? filterMaxLength
					: null;
			if (minLen !== null && len < minLen) return false;
			if (maxLen !== null && len > maxLen) return false;
			return true;
		});
	});

	// --- Per-message tag chips shown on each card -------------------------
	function messageTags(msg: FullMessage): { label: string; class: string }[] {
		const out: { label: string; class: string }[] = [];
		if (hasUrl(msg)) out.push({ label: 'URL', class: 'bg-sky-500/15 text-sky-600' });
		if (hasMention(msg)) out.push({ label: '@', class: 'bg-emerald-500/15 text-emerald-600' });
		if (hasCommand(msg)) out.push({ label: '!cmd', class: 'bg-amber-500/15 text-amber-600' });
		if (hasEmote(msg)) out.push({ label: 'emote', class: 'bg-purple-500/15 text-purple-600' });
		if (isReply(msg)) out.push({ label: 'reply', class: 'bg-teal-500/15 text-teal-600' });
		if (isFirstMsg(msg)) out.push({ label: 'first', class: 'bg-rose-500/15 text-rose-600' });
		if (isReturningChatter(msg))
			out.push({ label: 'returning', class: 'bg-indigo-500/15 text-indigo-600' });
		return out;
	}

	const operations: { value: Operation; label: string }[] = [
		{ value: 'channels', label: 'Get Channels' },
		{ value: 'capabilities', label: 'Get Capabilities' },
		{ value: 'list', label: 'Get List' },
		{ value: 'namehistory', label: 'Name History' },
		{ value: 'stats/user', label: 'User Stats' },
		{ value: 'stats/channel', label: 'Channel Stats' },
		{ value: 'search', label: 'Search Logs' },
		{ value: 'logs/channel', label: 'Channel Logs' },
		{ value: 'logs/user', label: 'User Logs' },
		{ value: 'logs/channel/date', label: 'Channel Logs by Date' },
		{ value: 'logs/user/month', label: 'User Logs by Month' },
		{ value: 'random/channel', label: 'Random Channel Message' },
		{ value: 'random/user', label: 'Random User Message' },
		{ value: 'optout', label: 'Opt Out' }
	];

	const needsChannel = $derived(
		[
			'list',
			'stats/channel',
			'stats/user',
			'search',
			'logs/channel',
			'logs/user',
			'logs/channel/date',
			'logs/user/month',
			'random/channel',
			'random/user'
		].includes(operation)
	);
	const needsUser = $derived(
		['stats/user', 'search', 'logs/user', 'logs/user/month', 'random/user'].includes(operation)
	);
	const needsQuery = $derived(operation === 'search');
	const needsDateRange = $derived(
		['stats/user', 'stats/channel', 'logs/channel', 'logs/user'].includes(operation)
	);
	const needsPagination = $derived(
		[
			'search',
			'logs/channel',
			'logs/user',
			'logs/channel/date',
			'logs/user/month',
			'random/channel',
			'random/user'
		].includes(operation)
	);
	const needsUserId = $derived(operation === 'namehistory');
	const needsDateParts = $derived(['logs/channel/date', 'logs/user/month'].includes(operation));
	const needsChannelValue = $derived(needsChannel && operation !== 'list');

	/** Operations whose results land in `messages` and can be filtered. */
	const messagesOperations = new Set<Operation>([
		'search',
		'logs/channel',
		'logs/user',
		'logs/channel/date',
		'logs/user/month',
		'random/channel',
		'random/user'
	]);
	const showFilters = $derived(messagesOperations.has(operation));

	function clearResults() {
		error = '';
		result = '';
		messages = [];
		statsUser = null;
		statsChannel = null;
		nameHistory = [];
		rawResult = [];
		// Clearing results also resets filters, since they only make sense
		// for the current message set.
		clearFilters();
	}

	/**
	 * `datetime-local` yields a timezone-less `YYYY-MM-DDTHH:mm`, which the
	 * upstream API would read as a naive datetime. Interpret it as local time
	 * and send UTC RFC 3339 (with offset) instead.
	 */
	function toRFC3339(value: string): string | undefined {
		if (!value) return undefined;
		const d = new Date(value);
		return Number.isNaN(d.getTime()) ? undefined : d.toISOString();
	}

	/** Client-side required-field checks so empty inputs don't surface as server 422/404s. */
	function validate(): string | null {
		if (needsChannelValue && !channel.trim()) return 'Channel is required for this operation.';
		if (needsUser && !user.trim()) return 'User is required for this operation.';
		if (needsQuery && !query.trim()) return 'Search query is required.';
		if (needsUserId && !userId.trim()) return 'User ID is required.';
		if (needsDateParts) {
			if (!year.trim() || !month.trim()) return 'Year and month are required.';
			if (operation === 'logs/channel/date' && !day.trim()) return 'Day is required.';
		}
		return null;
	}

	async function execute() {
		clearResults();
		loading = true;

		const validationError = validate();
		if (validationError) {
			error = validationError;
			loading = false;
			return;
		}

		const limitNum = parseInt(limit) || 50;
		const offsetNum = offset ? parseInt(offset) : undefined;
		const fromParam = toRFC3339(fromDate);
		const toParam = toRFC3339(toDate);

		try {
			switch (operation) {
				case 'channels': {
					const res = await api.harambelogs.getChannels();
					rawResult = res;
					break;
				}
				case 'capabilities': {
					const res = await api.harambelogs.getCapabilities();
					rawResult = res;
					break;
				}
				case 'list': {
					const res = await api.harambelogs.getList(channel || undefined);
					result = JSON.stringify(res, null, 2);
					break;
				}
				case 'namehistory': {
					const res = await api.harambelogs.getNameHistory(userId);
					nameHistory = res;
					break;
				}
				case 'stats/user': {
					const res = await api.harambelogs.getUserStats(
						channelType,
						channel,
						userType,
						user,
						fromParam,
						toParam
					);
					statsUser = res;
					break;
				}
				case 'stats/channel': {
					const res = await api.harambelogs.getChannelStats(
						channelType,
						channel,
						fromParam,
						toParam
					);
					statsChannel = res;
					break;
				}
				case 'search': {
					const res = await api.harambelogs.search(
						channelType,
						channel,
						userType,
						user,
						query,
						limitNum,
						offsetNum,
						reverse
					);
					messages = res.messages;
					if (messages.length === 0) error = 'No messages found.';
					break;
				}
				case 'logs/channel': {
					const res = await api.harambelogs.getChannelLogs(
						channelType,
						channel,
						fromParam,
						toParam,
						limitNum,
						offsetNum,
						reverse
					);
					messages = res.messages;
					break;
				}
				case 'logs/user': {
					const res = await api.harambelogs.getUserLogs(
						channelType,
						channel,
						userType,
						user,
						fromParam,
						toParam,
						limitNum,
						offsetNum,
						reverse
					);
					messages = res.messages;
					break;
				}
				case 'logs/channel/date': {
					const res = await api.harambelogs.getChannelLogsByDate(
						channelType,
						channel,
						year,
						month,
						day,
						limitNum,
						offsetNum,
						reverse
					);
					messages = res.messages;
					break;
				}
				case 'logs/user/month': {
					const res = await api.harambelogs.getUserLogsByMonth(
						channelType,
						channel,
						userType,
						user,
						year,
						month,
						limitNum,
						offsetNum,
						reverse
					);
					messages = res.messages;
					break;
				}
				case 'random/channel': {
					const res = await api.harambelogs.getChannelRandom(channelType, channel, limitNum);
					messages = res.messages;
					break;
				}
				case 'random/user': {
					const res = await api.harambelogs.getUserRandom(
						channelType,
						channel,
						userType,
						user,
						limitNum
					);
					messages = res.messages;
					break;
				}
				case 'optout': {
					const res = await api.harambelogs.optout();
					result = JSON.stringify(res, null, 2);
					break;
				}
			}
		} catch (e) {
			error = e instanceof Error ? e.message : String(e);
		} finally {
			loading = false;
		}
	}

	/** Copy the filtered message list as plain text — useful for reports. */
	async function copyFiltered() {
		const text = filteredMessages
			.map((m) => `[${new Date(m.timestamp).toISOString()}] ${m.displayName}: ${m.text}`)
			.join('\n');
		try {
			await navigator.clipboard.writeText(text);
		} catch {
			// Clipboard may be unavailable; silently ignore.
		}
	}

	/** Export filtered messages as JSON. */
	function downloadFilteredJson() {
		const blob = new Blob([JSON.stringify(filteredMessages, null, 2)], {
			type: 'application/json'
		});
		const url = URL.createObjectURL(blob);
		const a = document.createElement('a');
		a.href = url;
		a.download = `harambelogs_${operation}_${Date.now()}.json`;
		document.body.appendChild(a);
		a.click();
		a.remove();
		URL.revokeObjectURL(url);
	}
</script>

<Card class="w-120 shadow-xl backdrop-blur-sm">
	<Header class="pt-6">
		<Title class="text-center text-2xl font-bold">Harambelogs API</Title>
		<p class="text-muted-foreground text-center text-sm">Full API access</p>
	</Header>
	<Content class="space-y-4 p-6">
		<!-- Operation selector -->
		<div>
			<Label for="hl-operation">Operation</Label>
			<select
				id="hl-operation"
				bind:value={operation}
				onchange={() => clearResults()}
				class="border-input bg-background ring-offset-background focus-visible:ring-ring mt-1 flex h-9 w-full rounded-md border px-3 py-1 text-sm shadow-xs transition-colors focus-visible:ring-2 focus-visible:ring-offset-2 focus-visible:outline-none"
			>
				{#each operations as op (op.value)}
					<option value={op.value}>{op.label}</option>
				{/each}
			</select>
		</div>

		<!-- User ID (namehistory only) -->
		{#if needsUserId}
			<div>
				<Label for="hl-userid">User ID</Label>
				<Input id="hl-userid" bind:value={userId} placeholder="e.g., 26093170" class="mt-1" />
			</div>
		{/if}

		<!-- Channel/User type selectors -->
		{#if needsChannel}
			<div class="grid grid-cols-2 gap-3">
				<div>
					<Label for="hl-channel-type">Channel Type</Label>
					<select
						id="hl-channel-type"
						bind:value={channelType}
						class="border-input bg-background ring-offset-background focus-visible:ring-ring mt-1 flex h-9 w-full rounded-md border px-3 py-1 text-sm shadow-xs transition-colors focus-visible:ring-2 focus-visible:ring-offset-2 focus-visible:outline-none"
					>
						<option value="channel">channel</option>
						<option value="channelid">channelid</option>
					</select>
				</div>
				<div>
					<Label for="hl-channel">Channel</Label>
					<Input id="hl-channel" bind:value={channel} class="mt-1" />
				</div>
			</div>
		{/if}

		{#if needsUser}
			<div class="grid grid-cols-2 gap-3">
				<div>
					<Label for="hl-user-type">User Type</Label>
					<select
						id="hl-user-type"
						bind:value={userType}
						class="border-input bg-background ring-offset-background focus-visible:ring-ring mt-1 flex h-9 w-full rounded-md border px-3 py-1 text-sm shadow-xs transition-colors focus-visible:ring-2 focus-visible:ring-offset-2 focus-visible:outline-none"
					>
						<option value="user">user</option>
						<option value="userid">userid</option>
					</select>
				</div>
				<div>
					<Label for="hl-user">User</Label>
					<Input id="hl-user" bind:value={user} class="mt-1" />
				</div>
			</div>
		{/if}

		<!-- Search query -->
		{#if needsQuery}
			<div>
				<Label for="hl-query">Search Query</Label>
				<Input
					id="hl-query"
					bind:value={query}
					class="mt-1"
					placeholder="e.g., LULW"
					onkeydown={(e) => {
						if (e.key === 'Enter') void execute();
					}}
				/>
			</div>
		{/if}

		<!-- Date range -->
		{#if needsDateRange}
			<div class="grid grid-cols-2 gap-3">
				<div>
					<Label for="hl-from">From</Label>
					<Input id="hl-from" type="datetime-local" bind:value={fromDate} class="mt-1" />
				</div>
				<div>
					<Label for="hl-to">To</Label>
					<Input id="hl-to" type="datetime-local" bind:value={toDate} class="mt-1" />
				</div>
			</div>
		{/if}

		<!-- Date parts (year/month/day) -->
		{#if needsDateParts}
			<div class="grid grid-cols-3 gap-3">
				<div>
					<Label for="hl-year">Year</Label>
					<Input id="hl-year" bind:value={year} placeholder="2024" class="mt-1" />
				</div>
				<div>
					<Label for="hl-month">Month</Label>
					<Input id="hl-month" bind:value={month} placeholder="01" class="mt-1" />
				</div>
				{#if operation === 'logs/channel/date'}
					<div>
						<Label for="hl-day">Day</Label>
						<Input id="hl-day" bind:value={day} placeholder="15" class="mt-1" />
					</div>
				{/if}
			</div>
		{/if}

		<!-- Pagination -->
		{#if needsPagination}
			<div class="grid grid-cols-3 gap-3">
				<div>
					<Label for="hl-limit">Limit</Label>
					<Input id="hl-limit" type="number" min="1" max="1000" bind:value={limit} class="mt-1" />
				</div>
				<div>
					<Label for="hl-offset">Offset</Label>
					<Input
						id="hl-offset"
						type="number"
						min="0"
						bind:value={offset}
						class="mt-1"
						placeholder="0"
					/>
				</div>
				<div class="flex items-end pb-2">
					<label class="flex cursor-pointer items-center gap-2 text-sm">
						<input
							type="checkbox"
							bind:checked={reverse}
							class="accent-primary h-4 w-4 rounded border-gray-300"
						/>
						<span>Reverse</span>
					</label>
				</div>
			</div>
		{/if}

		<!-- Execute button -->
		<Button onclick={execute} disabled={loading || !backend.ready} class="w-full">
			{loading ? 'Executing…' : 'Execute'}
		</Button>

		<!-- Error -->
		{#if error}
			<p class="text-destructive text-center text-sm">{error}</p>
		{/if}

		<!-- ─── Filter panel (only for message-returning operations) ─────── -->
		{#if showFilters && messages.length > 0}
			<details class="border-border/60 group rounded-md border" bind:open={filtersOpen}>
				<summary
					class="hover:bg-muted/50 flex cursor-pointer items-center justify-between rounded-md px-3 py-2 text-sm font-medium"
				>
					<span class="flex items-center gap-2">
						Filters
						{#if activeFilterCount > 0}
							<span
								class="bg-primary text-primary-foreground rounded-full px-1.5 py-0.5 text-[10px] font-medium"
							>
								{activeFilterCount} active
							</span>
						{/if}
					</span>
					<span class="text-muted-foreground text-xs group-open:hidden">
						{filteredMessages.length} / {messages.length} shown
					</span>
				</summary>

				<div class="space-y-3 border-t p-3">
					<!-- Free-text search -->
					<div>
						<Label for="hl-filter-text" class="text-xs">Contains text</Label>
						<Input
							id="hl-filter-text"
							bind:value={filterText}
							placeholder="substring match (case-insensitive)"
							class="mt-1 h-8 text-xs"
						/>
					</div>

					<!-- Username filter -->
					<div>
						<Label for="hl-filter-user" class="text-xs">From user</Label>
						<Input
							id="hl-filter-user"
							bind:value={filterUsername}
							placeholder="partial username"
							class="mt-1 h-8 text-xs"
						/>
					</div>

					<!-- Toggle grid -->
					<div class="grid grid-cols-2 gap-1.5 sm:grid-cols-3">
						<label
							class="hover:bg-muted border-border/60 flex cursor-pointer items-center gap-2 rounded-md border px-2 py-1.5 text-xs"
						>
							<input
								type="checkbox"
								bind:checked={filterContainsUrl}
								class="accent-primary size-3.5"
							/>
							<span>URLs only</span>
						</label>
						<label
							class="hover:bg-muted border-border/60 flex cursor-pointer items-center gap-2 rounded-md border px-2 py-1.5 text-xs"
						>
							<input
								type="checkbox"
								bind:checked={filterContainsMention}
								class="accent-primary size-3.5"
							/>
							<span>@mentions only</span>
						</label>
						<label
							class="hover:bg-muted border-border/60 flex cursor-pointer items-center gap-2 rounded-md border px-2 py-1.5 text-xs"
						>
							<input
								type="checkbox"
								bind:checked={filterContainsCommand}
								class="accent-primary size-3.5"
							/>
							<span>!commands only</span>
						</label>
						<label
							class="hover:bg-muted border-border/60 flex cursor-pointer items-center gap-2 rounded-md border px-2 py-1.5 text-xs"
						>
							<input
								type="checkbox"
								bind:checked={filterContainsEmote}
								class="accent-primary size-3.5"
							/>
							<span>Emotes only</span>
						</label>
						<label
							class="hover:bg-muted border-border/60 flex cursor-pointer items-center gap-2 rounded-md border px-2 py-1.5 text-xs"
						>
							<input
								type="checkbox"
								bind:checked={filterContainsNumber}
								class="accent-primary size-3.5"
							/>
							<span>Numbers</span>
						</label>
						<label
							class="hover:bg-muted border-border/60 flex cursor-pointer items-center gap-2 rounded-md border px-2 py-1.5 text-xs"
						>
							<input
								type="checkbox"
								bind:checked={filterOnlyReplies}
								class="accent-primary size-3.5"
							/>
							<span>Replies only</span>
						</label>
						<label
							class="hover:bg-muted border-border/60 flex cursor-pointer items-center gap-2 rounded-md border px-2 py-1.5 text-xs"
						>
							<input
								type="checkbox"
								bind:checked={filterOnlyFirstMsg}
								class="accent-primary size-3.5"
							/>
							<span>First-time chatters</span>
						</label>
						<label
							class="hover:bg-muted border-border/60 flex cursor-pointer items-center gap-2 rounded-md border px-2 py-1.5 text-xs"
						>
							<input
								type="checkbox"
								bind:checked={filterOnlyReturning}
								class="accent-primary size-3.5"
							/>
							<span>Returning chatters</span>
						</label>
					</div>

					<!-- Length range -->
					<div class="grid grid-cols-2 gap-3">
						<div>
							<Label for="hl-filter-minlen" class="text-xs">Min length</Label>
							<Input
								id="hl-filter-minlen"
								type="number"
								min="0"
								bind:value={filterMinLength}
								placeholder="0"
								class="mt-1 h-8 text-xs"
							/>
						</div>
						<div>
							<Label for="hl-filter-maxlen" class="text-xs">Max length</Label>
							<Input
								id="hl-filter-maxlen"
								type="number"
								min="0"
								bind:value={filterMaxLength}
								placeholder="∞"
								class="mt-1 h-8 text-xs"
							/>
						</div>
					</div>

					<!-- Actions -->
					<div class="flex flex-wrap items-center justify-between gap-2 border-t pt-3">
						<Button
							size="sm"
							variant="outline"
							onclick={clearFilters}
							disabled={activeFilterCount === 0}
						>
							Clear filters
						</Button>
						<div class="flex gap-2">
							<Button size="sm" variant="outline" onclick={copyFiltered}>Copy as text</Button>
							<Button size="sm" variant="outline" onclick={downloadFilteredJson}>
								Export JSON
							</Button>
						</div>
					</div>
				</div>
			</details>
		{/if}

		<!-- Results: Messages -->
		{#if messages.length > 0}
			<div class="space-y-2">
				<div class="text-muted-foreground flex items-baseline justify-between text-xs">
					<span>
						{#if activeFilterCount > 0}
							Showing <strong class="text-foreground">{filteredMessages.length}</strong>
							of {messages.length} messages
						{:else}
							{messages.length} messages
						{/if}
					</span>
					{#if activeFilterCount > 0 && filteredMessages.length === 0}
						<span class="text-amber-500">no messages match the current filters</span>
					{/if}
				</div>

				<div
					class="bg-muted border-border/50 max-h-96 space-y-2 overflow-auto rounded border p-3 text-xs"
				>
					{#each filteredMessages as msg (msg.id)}
						{@const tags = messageTags(msg)}
						<div class="border-border/30 border-b pb-1.5 last:border-0">
							<div class="flex items-baseline justify-between gap-2">
								<span class="text-primary truncate font-bold">{msg.displayName}</span>
								<span class="text-muted-foreground shrink-0 text-[10px]">
									{new Date(msg.timestamp).toLocaleString()}
								</span>
							</div>
							<p class="mt-0.5 break-words">{msg.text}</p>
							{#if tags.length > 0}
								<div class="mt-1 flex flex-wrap gap-1">
									{#each tags as t (t.label)}
										<span class="rounded px-1.5 py-0.5 text-[9px] font-medium {t.class}">
											{t.label}
										</span>
									{/each}
								</div>
							{/if}
						</div>
					{/each}
				</div>
			</div>
		{/if}

		<!-- Results: User Stats -->
		{#if statsUser}
			<div class="bg-muted rounded border p-3 text-sm">
				<p><strong>User ID:</strong> {statsUser.userId}</p>
				<p><strong>Login:</strong> {statsUser.userLogin ?? 'N/A'}</p>
				<p><strong>Messages:</strong> {statsUser.messageCount.toLocaleString()}</p>
			</div>
		{/if}

		<!-- Results: Channel Stats -->
		{#if statsChannel}
			<div class="bg-muted max-h-48 overflow-auto rounded border p-3 text-sm">
				<p><strong>Total Messages:</strong> {statsChannel.messageCount.toLocaleString()}</p>
				{#if statsChannel.topChatters.length > 0}
					<p class="mt-2 font-semibold">Top Chatters:</p>
					{#each statsChannel.topChatters.slice(0, 10) as tc (tc.userId)}
						<p class="text-xs">{tc.userLogin ?? tc.userId}: {tc.messageCount.toLocaleString()}</p>
					{/each}
				{/if}
			</div>
		{/if}

		<!-- Results: Name History -->
		{#if nameHistory.length > 0}
			<div class="bg-muted max-h-48 overflow-auto rounded border p-3 text-sm">
				{#each nameHistory as nh (nh.user_login + nh.first_timestamp)}
					<p class="text-xs">
						{nh.user_login} — {new Date(nh.first_timestamp).toLocaleDateString()} to {new Date(
							nh.last_timestamp
						).toLocaleDateString()}
					</p>
				{/each}
			</div>
		{/if}

		<!-- Results: Raw string array -->
		{#if rawResult.length > 0}
			<div class="bg-muted max-h-48 overflow-auto rounded border p-3 text-xs">
				{#each rawResult as item (item)}
					<p>{item}</p>
				{/each}
			</div>
		{/if}

		<!-- Results: JSON -->
		{#if result}
			<pre class="bg-muted max-h-48 overflow-auto rounded p-3 text-xs">{result}</pre>
		{/if}
	</Content>
</Card>
