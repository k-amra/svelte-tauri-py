<script lang="ts">
	import { onMount } from 'svelte';
	import { backend } from '$lib/api/backend.svelte';
	import AppNav from '$lib/components/AppNav.svelte';
	import { DEFAULT_VIEW, views } from '$lib/views';

	// App owns the global backend lifecycle (init once, dispose on unmount).
	onMount(() => {
		void backend.init();
		return () => {
			void backend.dispose();
		};
	});

	let activeId = $state(DEFAULT_VIEW);
	const activeView = $derived(views.find((v) => v.id === activeId) ?? views[0]);
</script>

<div class="bg-background text-foreground flex h-screen select-none">
	<AppNav {views} bind:activeId />
	<main class="flex-1 overflow-y-auto">
		<div class="mx-auto flex max-w-5xl justify-center p-6">
			<activeView.component />
		</div>
	</main>
</div>
