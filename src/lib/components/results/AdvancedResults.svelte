<script lang="ts">
	import type { ChatStatsResult } from '$lib/api/chatStats';

	let { stats, isPerUser }: { stats: ChatStatsResult; isPerUser: boolean } = $props();

	const maxMentionDegree = $derived(
		stats.mention_graph.length > 0 ? Math.max(...stats.mention_graph.map((d) => d.degree)) : 1
	);
	const maxMutualTotal = $derived(
		stats.mutual_mention_pairs.length > 0
			? Math.max(...stats.mutual_mention_pairs.map((p) => p.total))
			: 1
	);
	const maxEmoteCentrality = $derived(
		stats.emote_centrality.length > 0
			? Math.max(...stats.emote_centrality.map((c) => c.distinct_co_occurrences))
			: 1
	);
	const maxBotScore = $derived(
		stats.bot_likelihood.length > 0 ? Math.max(...stats.bot_likelihood.map((b) => b.score)) : 1
	);
	const maxQuoteReply = $derived(
		stats.quote_reply_pairs.length > 0
			? Math.max(...stats.quote_reply_pairs.map((p) => p.count))
			: 1
	);
</script>

{#if stats.mention_graph.length > 0}
	<div>
		<p class="border-border/60 mb-2 border-b pb-1 text-sm font-medium">
			Mention graph (in/out degree)
		</p>
		<div class="space-y-1">
			{#each stats.mention_graph as node (node.username)}
				<div class="flex items-center gap-2 text-xs">
					<span class="w-24 truncate" title="in {node.mentions_in} / out {node.mentions_out}"
						>{node.username}</span
					>
					<div class="bg-muted h-3 flex-1 overflow-hidden rounded-full">
						<div
							class="h-full rounded-full bg-emerald-500 transition-[width] duration-300"
							style="width: {(node.degree / maxMentionDegree) * 100}%"
						></div>
					</div>
					<span class="w-12 text-right">{node.degree}</span>
				</div>
			{/each}
		</div>
	</div>
{/if}

{#if !isPerUser && stats.mutual_mention_pairs.length > 0}
	<div>
		<p class="border-border/60 mb-2 border-b pb-1 text-sm font-medium">Mutual mentions</p>
		<div class="space-y-1">
			{#each stats.mutual_mention_pairs as p (`${p.user_a}-${p.user_b}`)}
				<div class="flex items-center gap-2 text-xs">
					<span class="w-32 truncate" title="{p.user_a} ↔ {p.user_b}">{p.user_a} ↔ {p.user_b}</span>
					<div class="bg-muted h-3 flex-1 overflow-hidden rounded-full">
						<div
							class="h-full rounded-full bg-emerald-500 transition-[width] duration-300"
							style="width: {(p.total / maxMutualTotal) * 100}%"
						></div>
					</div>
					<span class="w-16 text-right">{p.count_ab}/{p.count_ba}</span>
				</div>
			{/each}
		</div>
	</div>
{/if}

{#if stats.emote_centrality.length > 0}
	<div>
		<p class="border-border/60 mb-2 border-b pb-1 text-sm font-medium">
			Emote centrality (distinct co-occurrences)
		</p>
		<div class="space-y-1">
			{#each stats.emote_centrality as c (c.emote)}
				<div class="flex items-center gap-2 text-xs">
					<span class="w-24 truncate">{c.emote}</span>
					<div class="bg-muted h-3 flex-1 overflow-hidden rounded-full">
						<div
							class="h-full rounded-full bg-purple-500 transition-[width] duration-300"
							style="width: {(c.distinct_co_occurrences / maxEmoteCentrality) * 100}%"
						></div>
					</div>
					<span class="w-12 text-right">{c.distinct_co_occurrences}</span>
				</div>
			{/each}
		</div>
	</div>
{/if}

{#if stats.bot_likelihood.length > 0}
	<div>
		<p class="border-border/60 mb-2 border-b pb-1 text-sm font-medium">
			Bot likelihood (heuristic)
		</p>
		<div class="space-y-1">
			{#each stats.bot_likelihood as b (b.user_id)}
				<div class="flex items-center gap-2 text-xs">
					<span class="w-24 truncate" title={b.signals.join(', ')}>{b.username}</span>
					<div class="bg-muted h-3 flex-1 overflow-hidden rounded-full">
						<div
							class="h-full rounded-full bg-red-500 transition-[width] duration-300"
							style="width: {(b.score / maxBotScore) * 100}%"
						></div>
					</div>
					<span class="w-12 text-right">{b.score.toFixed(2)}</span>
					<span class="text-muted-foreground truncate">{b.signals.join(', ')}</span>
				</div>
			{/each}
		</div>
	</div>
{/if}

{#if stats.quote_reply_pairs.length > 0}
	<div>
		<div class="border-border/60 mb-2 flex items-baseline justify-between border-b pb-1">
			<p class="text-sm font-medium">Quote replies</p>
			<span class="text-muted-foreground text-xs">{stats.quote_reply_count} inferred</span>
		</div>
		<div class="space-y-1">
			{#each stats.quote_reply_pairs as p (`${p.from_user}-${p.to_user}`)}
				<div class="flex items-center gap-2 text-xs">
					<span class="w-32 truncate">{p.from_user} → {p.to_user}</span>
					<div class="bg-muted h-3 flex-1 overflow-hidden rounded-full">
						<div
							class="h-full rounded-full bg-teal-500 transition-[width] duration-300"
							style="width: {(p.count / maxQuoteReply) * 100}%"
						></div>
					</div>
					<span class="w-12 text-right">{p.count}</span>
				</div>
			{/each}
		</div>
	</div>
{/if}
