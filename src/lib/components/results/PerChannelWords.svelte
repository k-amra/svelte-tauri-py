<script lang="ts">
	import type { ChannelSummary } from '$lib/api/chatStats';

	let { summary }: { summary: ChannelSummary } = $props();

	const max = $derived(
		summary.top_words.length > 0 ? Math.max(...summary.top_words.map((w) => w.count)) : 1
	);
</script>

{#if summary.top_words.length > 0}
	<ul class="space-y-1 text-xs">
		{#each summary.top_words.slice(0, 5) as w (w.word)}
			<li class="flex items-center gap-2">
				<span class="w-20 truncate" title={w.word}>{w.word}</span>
				<div class="bg-muted h-2 flex-1 overflow-hidden rounded-full">
					<div
						class="h-full rounded-full bg-teal-500"
						style="width: {(w.count / max) * 100}%"
					></div>
				</div>
				<span class="text-muted-foreground w-12 text-right tabular-nums">
					{w.count.toLocaleString()}
				</span>
			</li>
		{/each}
	</ul>
{:else}
	<p class="text-muted-foreground text-xs">No words</p>
{/if}
