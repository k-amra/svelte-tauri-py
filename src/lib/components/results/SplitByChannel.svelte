<script lang="ts">
	import type { ChannelSummary } from '$lib/api/chatStats';
	import type { Component } from 'svelte';

	let {
		summaries,
		title,
		row
	}: {
		summaries: ChannelSummary[];
		title: string;
		row: Component<{ summary: ChannelSummary }>;
	} = $props();
</script>

<div class="lg:col-span-2">
	<p class="border-border/60 mb-2 border-b pb-1 text-sm font-medium">{title}</p>
	<div class="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
		{#each summaries as s (s.channel)}
			{@const Row = row}
			<div class="bg-muted/40 border-border/60 rounded-lg border p-3">
				<p class="mb-2 truncate text-xs font-medium" title={s.channel}>{s.channel}</p>
				<Row summary={s} />
			</div>
		{/each}
	</div>
</div>
