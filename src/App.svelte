<script lang="ts">
	import { onMount } from 'svelte';
	import { backend } from '$lib/api/backend.svelte';
	import HelloWorld from '$lib/components/HelloWorld.svelte';
	import HarambelogsPanel from '$lib/components/HarambelogsPanel.svelte';
	import ScriptsPanel from '$lib/components/ScriptsPanel.svelte';

	// App owns the global backend lifecycle (init once, dispose on unmount).
	onMount(() => {
		void backend.init();
		return () => {
			void backend.dispose();
		};
	});
</script>

<main
	class="bg-background flex min-h-screen flex-wrap items-center justify-center gap-6 p-4 select-none"
>
	<HelloWorld />
	<ScriptsPanel />
	<HarambelogsPanel />
</main>
