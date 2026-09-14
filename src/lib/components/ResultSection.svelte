<script lang="ts">
	import { ChevronDown } from '@lucide/svelte';
	import type { Snippet } from 'svelte';

	let {
		id,
		title,
		subtitle = '',
		open = true,
		children
	}: {
		id: string;
		title: string;
		subtitle?: string;
		open?: boolean;
		children: Snippet;
	} = $props();
</script>

<details {id} {open} class="border-border/60 group scroll-mt-20 rounded-md border lg:col-span-2">
	<summary
		class="hover:bg-muted/50 flex cursor-pointer items-center justify-between rounded-md px-4 py-2.5"
	>
		<div class="flex items-baseline gap-2">
			<span class="text-sm font-medium">{title}</span>
			{#if subtitle}
				<span class="text-muted-foreground text-xs font-normal">{subtitle}</span>
			{/if}
		</div>
		<ChevronDown
			class="text-muted-foreground size-4 shrink-0 transition-transform group-open:rotate-180"
		/>
	</summary>
	<div class="border-border/60 border-t p-4">
		<div class="grid grid-cols-1 gap-x-6 gap-y-5 lg:grid-cols-2">
			{@render children()}
		</div>
	</div>
</details>
