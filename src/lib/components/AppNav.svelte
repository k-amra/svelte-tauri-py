<script lang="ts">
	import { backend } from '$lib/api/backend.svelte';
	import { theme } from '$lib/theme.svelte';
	import { cn } from '$lib/utils.js';
	import type { ViewDefinition } from '$lib/views';
	import { Monitor, Moon, Sun } from '@lucide/svelte';

	let { views, activeId = $bindable() }: { views: ViewDefinition[]; activeId: string } = $props();

	const themeLabel = $derived(
		theme.value === 'system' ? 'Theme: system' : `Theme: ${theme.value}`
	);
	const ThemeIcon = $derived(
		theme.value === 'system' ? Monitor : theme.resolved === 'dark' ? Moon : Sun
	);

	const statusLabel = $derived(
		backend.status === 'ready'
			? `Backend ready :${backend.port}`
			: backend.status === 'detached'
				? 'Detached (no Tauri)'
				: backend.status === 'error'
					? 'Backend error'
					: 'Backend starting…'
	);
	const dotClass = $derived(
		backend.status === 'ready'
			? 'bg-green-500'
			: backend.status === 'error'
				? 'bg-red-500'
				: 'animate-pulse bg-amber-400'
	);
</script>

<aside
	class="bg-sidebar text-sidebar-foreground border-sidebar-border flex w-56 shrink-0 flex-col border-r"
>
	<div class="border-sidebar-border flex items-center justify-between border-b p-4">
		<div>
			<p class="text-sm font-semibold">tauri2-svelte5-shadcn</p>
			<p class="text-sidebar-foreground/60 text-xs">Log &amp; chat analytics</p>
		</div>
		<button
			type="button"
			onclick={() => theme.cycle()}
			title={themeLabel}
			aria-label={themeLabel}
			class="hover:bg-sidebar-accent hover:text-sidebar-accent-foreground text-sidebar-foreground/70 rounded-md p-1.5 transition-colors"
		>
			<ThemeIcon class="size-4" />
		</button>
	</div>

	<nav class="flex-1 space-y-1 overflow-y-auto p-3" aria-label="Views">
		{#each views as view (view.id)}
			{@const Icon = view.icon}
			<button
				type="button"
				onclick={() => (activeId = view.id)}
				aria-current={activeId === view.id ? 'page' : undefined}
				class={cn(
					'hover:bg-sidebar-accent hover:text-sidebar-accent-foreground flex w-full items-center gap-2 rounded-md px-3 py-2 text-left text-sm font-medium transition-colors',
					activeId === view.id
						? 'bg-sidebar-accent text-sidebar-accent-foreground'
						: 'text-sidebar-foreground/70'
				)}
			>
				<Icon class="size-4 shrink-0" />
				<span class="truncate">{view.label}</span>
			</button>
		{/each}
	</nav>

	<div class="border-sidebar-border border-t p-3">
		<div class="flex items-center gap-2 text-xs">
			<span class={cn('size-2 shrink-0 rounded-full', dotClass)} aria-hidden="true"></span>
			<span class="text-sidebar-foreground/70 truncate">{statusLabel}</span>
		</div>
	</div>
</aside>
