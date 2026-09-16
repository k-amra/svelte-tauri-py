<script lang="ts">
	import type { ChannelSummary, ChatStatsResult } from '$lib/api/chatStats';
	import SplitByChannel from '$lib/components/results/SplitByChannel.svelte';
	import PerChannelWords from '$lib/components/results/PerChannelWords.svelte';
	import PerChannelEmotes from '$lib/components/results/PerChannelEmotes.svelte';

	let {
		stats,
		summaries = []
	}: {
		stats: ChatStatsResult;
		summaries?: ChannelSummary[];
	} = $props();

	const isMultiChannel = $derived(summaries.length > 1);

	const maxWord = $derived(
		stats.top_words.length > 0 ? Math.max(...stats.top_words.map((w) => w.count)) : 1
	);
	const maxEmote = $derived(
		stats.top_emotes.length > 0 ? Math.max(...stats.top_emotes.map((e) => e.count)) : 1
	);
	const maxEmotePair = $derived(
		stats.top_emote_pairs.length > 0 ? Math.max(...stats.top_emote_pairs.map((p) => p.count)) : 1
	);
	const maxPhrase = $derived(
		stats.top_phrases.length > 0 ? Math.max(...stats.top_phrases.map((p) => p.count)) : 1
	);
	const topDiversity = $derived(stats.emote_diversity.slice(0, 5));
	const maxDiversity = $derived(
		topDiversity.length > 0 ? Math.max(1, ...topDiversity.map((d) => d.total_emote_uses)) : 1
	);
</script>

{#if isMultiChannel}
	<SplitByChannel {summaries} title="Top words (per channel)" row={PerChannelWords} />
{:else}
	<div>
		<div class="border-border/60 mb-2 flex items-baseline justify-between border-b pb-1">
			<p class="text-sm font-medium">Top words</p>
			{#if stats.hapax_ratio != null || stats.zipf_slope != null}
				<span class="text-muted-foreground text-xs">
					{#if stats.hapax_ratio != null}hapax {stats.hapax_ratio}{/if}{#if stats.zipf_slope != null}
						· Zipf {stats.zipf_slope}{/if}
				</span>
			{/if}
		</div>
		<div class="space-y-1">
			{#each stats.top_words as w (w.word)}
				<div class="flex items-center gap-2 text-xs">
					<span class="w-24 truncate">{w.word}</span>
					<div class="bg-muted h-3 flex-1 overflow-hidden rounded-full">
						<div
							class="h-full rounded-full bg-teal-500 transition-[width] duration-300"
							style="width: {(w.count / maxWord) * 100}%"
						></div>
					</div>
					<span class="w-12 text-right">{w.count.toLocaleString()}</span>
				</div>
			{/each}
		</div>
	</div>
{/if}

{#if isMultiChannel}
	<SplitByChannel {summaries} title="Top emotes (per channel)" row={PerChannelEmotes} />
{:else if stats.top_emotes.length > 0}
	<div>
		<p class="border-border/60 mb-2 border-b pb-1 text-sm font-medium">Top emotes</p>
		<div class="space-y-1">
			{#each stats.top_emotes as e (e.name)}
				<div class="flex items-center gap-2 text-xs">
					<span class="w-24 truncate" title={e.name}>{e.name}</span>
					<div class="bg-muted h-3 flex-1 overflow-hidden rounded-full">
						<div
							class="h-full rounded-full bg-purple-500 transition-[width] duration-300"
							style="width: {(e.count / maxEmote) * 100}%"
						></div>
					</div>
					<span class="w-12 text-right">{e.count.toLocaleString()}</span>
				</div>
			{/each}
		</div>
	</div>
{/if}

{#if stats.emote_diversity.length > 0}
	<div>
		<p class="border-border/60 mb-2 border-b pb-1 text-sm font-medium">
			Emote diversity (Twitch emotes, 5+ uses)
		</p>
		<div class="space-y-1">
			{#each topDiversity as d (d.user_id)}
				<div class="flex items-center gap-2 text-xs">
					<span class="w-24 truncate" title="{d.unique_emotes} unique / {d.total_emote_uses} uses"
						>{d.username}</span
					>
					<div class="bg-muted h-3 flex-1 overflow-hidden rounded-full">
						<div
							class="h-full rounded-full bg-purple-500 transition-[width] duration-300"
							style="width: {(d.total_emote_uses / maxDiversity) * 100}%"
						></div>
					</div>
					<span class="w-12 text-right">{d.diversity_ratio.toFixed(2)}</span>
				</div>
			{/each}
		</div>
	</div>
{/if}

{#if stats.top_emote_pairs.length > 0}
	<div>
		<p class="border-border/60 mb-2 border-b pb-1 text-sm font-medium">Top emote pairs</p>
		<div class="space-y-1">
			{#each stats.top_emote_pairs as p (`${p.emote1}+${p.emote2}`)}
				<div class="flex items-center gap-2 text-xs">
					<span class="w-24 truncate">{p.emote1} + {p.emote2}</span>
					<div class="bg-muted h-3 flex-1 overflow-hidden rounded-full">
						<div
							class="h-full rounded-full bg-purple-500 transition-[width] duration-300"
							style="width: {(p.count / maxEmotePair) * 100}%"
						></div>
					</div>
					<span class="w-12 text-right">{p.count.toLocaleString()}</span>
				</div>
			{/each}
		</div>
	</div>
{/if}

{#if stats.top_phrases.length > 0}
	<div>
		<p class="border-border/60 mb-2 border-b pb-1 text-sm font-medium">Top phrases</p>
		<div class="space-y-1">
			{#each stats.top_phrases as p (p.phrase)}
				<div class="flex items-center gap-2 text-xs">
					<span class="flex-1 truncate">{p.phrase}</span>
					<div class="bg-muted h-3 w-24 overflow-hidden rounded-full">
						<div
							class="h-full rounded-full bg-teal-500 transition-[width] duration-300"
							style="width: {(p.count / maxPhrase) * 100}%"
						></div>
					</div>
					<span class="w-12 text-right">{p.count.toLocaleString()}</span>
				</div>
			{/each}
		</div>
	</div>
{/if}

{#if stats.emote_entropy != null}
	<div class="text-xs">
		<p class="border-border/60 mb-2 border-b pb-1 text-sm font-medium">Emote entropy</p>
		<p class="text-muted-foreground">{stats.emote_entropy} bits</p>
	</div>
{/if}

{#if stats.message_length_trend_slope != null}
	<div class="text-xs">
		<p class="border-border/60 mb-2 border-b pb-1 text-sm font-medium">Message length trend</p>
		<p class="text-muted-foreground">
			{stats.message_length_trend_slope >= 0 ? '+' : ''}{stats.message_length_trend_slope} chars/day
		</p>
	</div>
{/if}
