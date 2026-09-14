<script lang="ts">
	import type { ChannelSummary } from '$lib/api/chatStats';

	let { summary }: { summary: ChannelSummary } = $props();

	const max = $derived(
		summary.top_mentions.length > 0 ? Math.max(...summary.top_mentions.map((m) => m.count)) : 1
	);
</script>

{#if summary.top_mentions.length > 0}
	<ul class="space-y-1 text-xs">
		{#each summary.top_mentions.slice(0, 5) as m (m.username)}
			<li class="flex items-center gap-2">
				<span class="w-20 truncate" title="@{m.username}">@{m.username}</span>
				<div class="bg-muted h-2 flex-1 overflow-hidden rounded-full">
					<div
						class="h-full rounded-full bg-emerald-500"
						style="width: {(m.count / max) * 100}%"
					></div>
				</div>
				<span class="text-muted-foreground w-12 text-right tabular-nums">
					{m.count.toLocaleString()}
				</span>
			</li>
		{/each}
	</ul>
{:else}
	<p class="text-muted-foreground text-xs">No mentions</p>
{/if}
