<script lang="ts">
	import HelloWorld from '$lib/components/HelloWorld.svelte';
	import HarambelogsPanel from '$lib/components/HarambelogsPanel.svelte';
	import ScriptsPanel from '$lib/components/ScriptsPanel.svelte';
</script>

<main
	class="flex min-h-screen flex-wrap items-center justify-center gap-6 bg-linear-to-br from-indigo-500 via-purple-500 to-pink-500 p-4 select-none"
>
	<HelloWorld />
	<ScriptsPanel />
	<HarambelogsPanel />
</main>
