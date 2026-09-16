<script lang="ts">
	import type { ChannelSummary } from '$lib/api/chatStats';

	let { summary }: { summary: ChannelSummary } = $props();

	const max = $derived(
		summary.top_domains.length > 0 ? Math.max(...summary.top_domains.map((d) => d.count)) : 1
	);
</script>

{#if summary.top_domains.length > 0}
	<ul class="space-y-1 text-xs">
		{#each summary.top_domains.slice(0, 5) as d (d.domain)}
			<li class="flex items-center gap-2">
				<span class="w-20 truncate" title={d.domain}>{d.domain}</span>
				<div class="bg-muted h-2 flex-1 overflow-hidden rounded-full">
					<div class="h-full rounded-full bg-sky-500" style="width: {(d.count / max) * 100}%"></div>
				</div>
				<span class="text-muted-foreground w-12 text-right tabular-nums">
					{d.count.toLocaleString()}
				</span>
			</li>
		{/each}
	</ul>
{:else}
	<p class="text-muted-foreground text-xs">No links</p>
{/if}
