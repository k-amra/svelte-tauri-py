<script lang="ts">
	import {
		comparisonModeLabel,
		type ChatStatsResult,
		type PreviousPeriod
	} from '$lib/api/chatStats';
	import { computeDelta, type Delta } from '$lib/api/deltas';

	let { stats, previous }: { stats: ChatStatsResult; previous: PreviousPeriod } = $props();

	interface Row {
		key: string;
		current: number;
		previous: number;
		delta: Delta | null;
	}

	function buildRoleRows(): Row[] {
		// Union of both windows so a brand-new role (e.g. first VIP) shows up.
		const keys = new Set([...Object.keys(previous.roles), ...stats.roles.map((r) => r.role)]);
		const rows: Row[] = [];
		for (const key of [...keys].sort()) {
			const curr = stats.roles.find((r) => r.role === key)?.messages ?? 0;
			const prev = previous.roles[key] ?? 0;
			rows.push({
				key,
				current: curr,
				previous: prev,
				delta: computeDelta(curr, prev, 'neutral')
			});
		}
		return rows;
	}

	function buildClassRows(): Row[] {
		const classKeys = [
			'questions',
			'exclamations',
			'all_caps',
			'emote_only',
			'short_messages',
			'long_messages'
		] as const;
		return classKeys.map((key) => {
			const curr = stats.message_classes[key];
			const prev = previous.message_classes[key] ?? 0;
			return {
				key,
				current: curr,
				previous: prev,
				delta: computeDelta(curr, prev, 'neutral')
			};
		});
	}

	function buildPlatformRows(): Row[] {
		const keys = ['twitch_clips', 'youtube', 'discord', 'x_twitter', 'kick', 'other'] as const;
		return keys.map((key) => {
			const curr = stats.platform_links[key];
			const prev = previous.platform_links[key] ?? 0;
			return {
				key,
				current: curr,
				previous: prev,
				delta: computeDelta(curr, prev, 'neutral')
			};
		});
	}

	function toneClass(tone: Delta['tone'] | undefined): string {
		if (tone === 'good') return 'text-green-600';
		if (tone === 'bad') return 'text-red-600';
		return 'text-muted-foreground';
	}

	const roleRows = $derived(buildRoleRows());
	const classRows = $derived(buildClassRows());
	const platformRows = $derived(buildPlatformRows());

	const selfRepDelta = $derived(
		computeDelta(stats.self_repetition_count, previous.self_repetition_count, 'lower-is-better')
	);
	const dupDelta = $derived(
		computeDelta(stats.duplicate_message_count, previous.duplicate_message_count, 'lower-is-better')
	);
	const nonAsciiDelta = $derived(
		computeDelta(stats.non_ascii_ratio, previous.non_ascii_ratio, 'neutral', 'percent')
	);
	const cpDelta = $derived(
		computeDelta(
			stats.cross_user_copy_paste_count,
			previous.cross_user_copy_paste_count,
			'lower-is-better'
		)
	);

	const hasAnyBaseline = $derived(previous.total_messages > 0);
</script>

{#if !hasAnyBaseline}
	<div class="border-border/60 rounded-md border border-dashed p-4 text-center text-xs">
		<p class="text-muted-foreground">
			No data in the previous period ({previous.from_date.slice(0, 10)} →
			{previous.to_date.slice(0, 10)}) — comparison is unavailable.
		</p>
	</div>
{:else}
	<div class="space-y-5 lg:col-span-2">
		<div class="border-border/60 border-b pb-1">
			<p class="text-sm font-medium">Comparison</p>
			<p class="text-muted-foreground text-xs">
				{comparisonModeLabel(previous.mode)} ({previous.from_date.slice(0, 10)} →
				{previous.to_date.slice(0, 10)})
			</p>
		</div>

		<div class="grid grid-cols-1 gap-x-6 gap-y-4 sm:grid-cols-2">
			<!-- Roles -->
			<div>
				<p class="text-muted-foreground mb-2 text-xs font-medium uppercase">Roles</p>
				<div class="space-y-1">
					{#each roleRows as r (r.key)}
						<div class="flex items-center gap-2 text-xs">
							<span class="w-24 truncate capitalize">{r.key}</span>
							<span class="flex-1 text-right tabular-nums">{r.current.toLocaleString()}</span>
							<span class="text-muted-foreground/60 w-4 text-center">·</span>
							<span class="w-20 text-right font-medium {toneClass(r.delta?.tone)}">
								{r.delta?.text ?? '—'}
							</span>
						</div>
					{/each}
				</div>
			</div>

			<!-- Platform links -->
			<div>
				<p class="text-muted-foreground mb-2 text-xs font-medium uppercase">Platform links</p>
				<div class="space-y-1">
					{#each platformRows as r (r.key)}
						<div class="flex items-center gap-2 text-xs">
							<span class="w-24 truncate capitalize">{r.key.replace('_', ' ')}</span>
							<span class="flex-1 text-right tabular-nums">{r.current.toLocaleString()}</span>
							<span class="text-muted-foreground/60 w-4 text-center">·</span>
							<span class="w-20 text-right font-medium {toneClass(r.delta?.tone)}">
								{r.delta?.text ?? '—'}
							</span>
						</div>
					{/each}
				</div>
			</div>
		</div>

		<!-- Message classes -->
		<div>
			<p class="text-muted-foreground mb-2 text-xs font-medium uppercase">Message classes</p>
			<div class="grid grid-cols-2 gap-x-4 gap-y-1 sm:grid-cols-3">
				{#each classRows as r (r.key)}
					<div class="flex items-center justify-between gap-2 text-xs">
						<span class="truncate capitalize">{r.key.replace('_', ' ')}</span>
						<span class="font-medium {toneClass(r.delta?.tone)}">{r.delta?.text ?? '—'}</span>
					</div>
				{/each}
			</div>
		</div>

		<!-- Top movers -->
		{#if previous.top_chatter_gainers.length > 0 || previous.top_chatter_losers.length > 0}
			<div class="grid grid-cols-1 gap-x-6 gap-y-4 sm:grid-cols-2">
				{#if previous.top_chatter_gainers.length > 0}
					<div>
						<p class="text-muted-foreground mb-2 text-xs font-medium uppercase">Top gainers</p>
						<div class="space-y-1">
							{#each previous.top_chatter_gainers as d (d.user_id)}
								<div class="flex items-center gap-2 text-xs">
									<span class="w-24 truncate" title={d.username}>{d.username}</span>
									<span class="flex-1 text-right tabular-nums">{d.current.toLocaleString()}</span>
									<span class="text-muted-foreground/70 w-24 text-right">
										was {d.previous.toLocaleString()}
									</span>
									<span class="w-16 text-right font-medium text-green-600">
										+{d.delta.toLocaleString()}
									</span>
								</div>
							{/each}
						</div>
					</div>
				{/if}
				{#if previous.top_chatter_losers.length > 0}
					<div>
						<p class="text-muted-foreground mb-2 text-xs font-medium uppercase">Top losers</p>
						<div class="space-y-1">
							{#each previous.top_chatter_losers as d (d.user_id)}
								<div class="flex items-center gap-2 text-xs">
									<span class="w-24 truncate" title={d.username}>{d.username}</span>
									<span class="flex-1 text-right tabular-nums">{d.current.toLocaleString()}</span>
									<span class="text-muted-foreground/70 w-24 text-right">
										was {d.previous.toLocaleString()}
									</span>
									<span class="w-16 text-right font-medium text-red-600">
										{d.delta.toLocaleString()}
									</span>
								</div>
							{/each}
						</div>
					</div>
				{/if}
			</div>
		{/if}

		<!-- Quality signals -->
		<div>
			<p class="text-muted-foreground mb-2 text-xs font-medium uppercase">Quality signals</p>
			<div class="grid grid-cols-2 gap-x-4 gap-y-1 text-xs sm:grid-cols-4">
				<div class="flex items-center justify-between gap-2">
					<span>self-repeats</span>
					<span class="font-medium {toneClass(selfRepDelta?.tone)}">
						{selfRepDelta?.text ?? '—'}
					</span>
				</div>
				<div class="flex items-center justify-between gap-2">
					<span>duplicates</span>
					<span class="font-medium {toneClass(dupDelta?.tone)}">{dupDelta?.text ?? '—'}</span>
				</div>
				<div class="flex items-center justify-between gap-2">
					<span>non-ASCII</span>
					<span class="font-medium {toneClass(nonAsciiDelta?.tone)}">
						{nonAsciiDelta?.text ?? '—'}
					</span>
				</div>
				<div class="flex items-center justify-between gap-2">
					<span>copy-paste</span>
					<span class="font-medium {toneClass(cpDelta?.tone)}">{cpDelta?.text ?? '—'}</span>
				</div>
			</div>
		</div>
	</div>
{/if}
