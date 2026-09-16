<script lang="ts">
	import type { ChannelSummary } from '$lib/api/chatStats';

	let { summary }: { summary: ChannelSummary } = $props();

	const max = $derived(
		summary.top_commands.length > 0 ? Math.max(...summary.top_commands.map((c) => c.count)) : 1
	);
</script>

{#if summary.top_commands.length > 0}
	<ul class="space-y-1 text-xs">
		{#each summary.top_commands.slice(0, 5) as c (c.name)}
			<li class="flex items-center gap-2">
				<span class="w-20 truncate" title="!{c.name}">!{c.name}</span>
				<div class="bg-muted h-2 flex-1 overflow-hidden rounded-full">
					<div
						class="h-full rounded-full bg-amber-500"
						style="width: {(c.count / max) * 100}%"
					></div>
				</div>
				<span class="text-muted-foreground w-12 text-right tabular-nums">
					{c.count.toLocaleString()}
				</span>
			</li>
		{/each}
	</ul>
{:else}
	<p class="text-muted-foreground text-xs">No commands</p>
{/if}
