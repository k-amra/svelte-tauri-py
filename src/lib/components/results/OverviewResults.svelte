<script lang="ts">
	import { type ChatStatsResult, comparisonModeLabel } from '$lib/api/chatStats';
	import ComparisonSection from '$lib/components/ComparisonSection.svelte';
	import ChannelSummaryCards from '$lib/components/ChannelSummaryCards.svelte';
	import { computeDelta, type Delta, type Direction, type Format } from '$lib/api/deltas';

	let {
		stats,
		isPerUser,
		onDrillUser,
		onDrillChannel
	}: {
		stats: ChatStatsResult;
		isPerUser: boolean;
		onDrillUser?: (username: string) => void;
		onDrillChannel?: (channel: string) => void;
	} = $props();

	const maxTop = $derived(
		stats.top_chatters.length > 0 ? Math.max(...stats.top_chatters.map((t) => t.messageCount)) : 1
	);

	type Tile = {
		label: string;
		value: string;
		testid?: string;
		title?: string;
		delta?: Delta | null;
	};

	const tiles = $derived.by<Tile[]>(() => {
		const prev = stats.previous_period;
		const d = (
			current: number | null | undefined,
			previous: number | null | undefined,
			direction: Direction,
			format: Format = 'int'
		): Delta | null =>
			prev && prev.total_messages > 0 ? computeDelta(current, previous, direction, format) : null;

		return [
			{
				label: 'messages',
				value: stats.total_messages.toLocaleString(),
				testid: 'cs-total',
				delta: d(stats.total_messages, prev?.total_messages, 'higher-is-better')
			},
			{
				label: 'chatters',
				value: stats.unique_chatters.toLocaleString(),
				delta: d(stats.unique_chatters, prev?.unique_chatters, 'higher-is-better')
			},
			{ label: 'days spanned', value: String(stats.days_spanned) },
			{
				label: 'avg length',
				value: stats.avg_message_length.toFixed(1),
				delta: d(stats.avg_message_length, prev?.avg_message_length, 'neutral', 'float1')
			},
			{
				label: 'median length',
				value: stats.median_message_length?.toFixed(1) ?? '—',
				delta: d(stats.median_message_length, prev?.median_message_length, 'neutral', 'float1')
			},
			{
				label: 'max length',
				value: stats.max_message_length?.toLocaleString() ?? '—',
				delta: d(stats.max_message_length, prev?.max_message_length, 'neutral')
			},
			{
				label: 'avg words / msg',
				value: stats.avg_words_per_message?.toFixed(1) ?? '—',
				delta: d(stats.avg_words_per_message, prev?.avg_words_per_message, 'neutral', 'float1')
			},
			{
				label: 'vocab richness',
				value: stats.vocab_richness?.toFixed(3) ?? '—',
				delta: d(stats.vocab_richness, prev?.vocab_richness, 'higher-is-better', 'float3')
			},
			{
				label: 'unique words',
				value: stats.unique_word_count.toLocaleString(),
				delta: d(stats.unique_word_count, prev?.unique_word_count, 'higher-is-better')
			},
			{
				label: 'peak concurrent (5m)',
				value: stats.peak_concurrent_chatters?.toLocaleString() ?? '—',
				title: stats.peak_concurrent_window
					? new Date(stats.peak_concurrent_window).toLocaleString()
					: undefined,
				delta: d(stats.peak_concurrent_chatters, prev?.peak_concurrent_chatters, 'higher-is-better')
			}
		];
	});
</script>

{#if stats.previous_period}
	<p class="text-muted-foreground text-center text-xs lg:col-span-2">
		{comparisonModeLabel(stats.previous_period.mode)}
		({stats.previous_period.from_date.slice(0, 10)} →
		{stats.previous_period.to_date.slice(0, 10)})
	</p>
	<ComparisonSection {stats} previous={stats.previous_period} />
{/if}

<div class="grid grid-cols-2 gap-2 text-center sm:grid-cols-3 lg:col-span-2 lg:grid-cols-5">
	{#each tiles as t (t.label)}
		<div class="bg-muted/60 rounded-lg p-2.5 text-center" title={t.title || undefined}>
			<div class="text-xl font-semibold tabular-nums" data-testid={t.testid || undefined}>
				{t.value}
			</div>
			<div class="text-muted-foreground text-[10px] tracking-wide uppercase">{t.label}</div>
			{#if t.delta}
				<div class="mt-0.5 flex items-baseline justify-center gap-1 text-[10px]">
					<span
						class="font-medium"
						class:text-green-600={t.delta.tone === 'good'}
						class:text-red-600={t.delta.tone === 'bad'}
						class:text-muted-foreground={t.delta.tone === 'flat'}
					>
						{t.delta.text}
					</span>
					<span class="text-muted-foreground/70">· {t.delta.previousText}</span>
				</div>
			{/if}
		</div>
	{/each}
</div>

{#if stats.channel_summaries.length > 1}
	<ChannelSummaryCards summaries={stats.channel_summaries} {onDrillChannel} />
{/if}

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
				Msgs/user p50 {stats.chatter_message_quantiles.p50}, p90 {stats.chatter_message_quantiles
					.p90}
			</span>
		{/if}
	</div>
{/if}

{#if !isPerUser}
	<div class="lg:col-span-2">
		<p class="border-border/60 mb-2 border-b pb-1 text-sm font-medium">Top chatters</p>
		<div class="space-y-1">
			{#each stats.top_chatters as t (t.user_id)}
				{@const channels = t.channels ?? []}
				{@const showChannels = channels.length > 0 && stats.channel_summaries.length > 1}
				<div class="flex items-center gap-2 text-xs">
					<button
						type="button"
						class="hover:text-primary w-20 truncate text-left hover:underline"
						disabled={!onDrillUser}
						title={t.engagement_score != null
							? `engagement ${t.engagement_score} · ${t.activeDays}d active${showChannels ? ` · in ${channels.join(', ')}` : ''}${onDrillUser ? ' · click to filter' : ''}`
							: `${t.activeDays}d active${showChannels ? ` · in ${channels.join(', ')}` : ''}${onDrillUser ? ' · click to filter' : ''}`}
						onclick={() => onDrillUser?.(t.username)}
					>
						{t.username}
					</button>
					{#if showChannels}
						<span
							class="bg-primary/10 text-primary max-w-24 shrink-0 truncate rounded-full px-1.5 py-0.5 text-[9px] font-medium"
							title="Active in: {channels.join(', ')}"
						>
							{channels.join('·')}
						</span>
					{/if}
					<div class="bg-muted h-3 flex-1 overflow-hidden rounded-full">
						<div
							class="h-full rounded-full bg-teal-500 transition-[width] duration-300"
							style="width: {(t.messageCount / maxTop) * 100}%"
						></div>
					</div>
					<span class="w-12 text-right">{t.messageCount.toLocaleString()}</span>
				</div>
			{/each}
		</div>
	</div>
{/if}
