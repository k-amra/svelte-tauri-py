<script lang="ts">
	import type { ChannelSummary } from '$lib/api/chatStats';

	let { summary }: { summary: ChannelSummary } = $props();

	const max = $derived(
		summary.top_emotes.length > 0 ? Math.max(...summary.top_emotes.map((e) => e.count)) : 1
	);
</script>

{#if summary.top_emotes.length > 0}
	<ul class="space-y-1 text-xs">
		{#each summary.top_emotes.slice(0, 5) as e (e.name)}
			<li class="flex items-center gap-2">
				<span class="w-20 truncate" title={e.name}>{e.name}</span>
				<div class="bg-muted h-2 flex-1 overflow-hidden rounded-full">
					<div
						class="h-full rounded-full bg-purple-500"
						style="width: {(e.count / max) * 100}%"
					></div>
				</div>
				<span class="text-muted-foreground w-12 text-right tabular-nums">
					{e.count.toLocaleString()}
				</span>
			</li>
		{/each}
	</ul>
{:else}
	<p class="text-muted-foreground text-xs">No emotes</p>
{/if}
