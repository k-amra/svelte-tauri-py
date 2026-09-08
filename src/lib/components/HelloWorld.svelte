<script lang="ts">
	import { FILES, GlobalState, preventDefault } from '$lib/commands.svelte';
	import { Input } from '$lib/components/ui/input/index';
	import { Button } from '$lib/components/ui/button/index';
	import { Card, Header, Title, Content } from '$lib/components/ui/card/index';

	const gs = new GlobalState();

	const handleSubmit = preventDefault(async () => {
		if (gs.nlen && gs.glen) {
			await gs.write(FILES.NAME_FILE, gs.name);
			await gs.write(FILES.GREET_FILE, gs.greet);
		}
	});

	const handleReset = async () => {
		gs.reset();
		await gs.write(FILES.NAME_FILE, '');
		await gs.write(FILES.GREET_FILE, '');
	};

	$effect(() => {
		gs.read(FILES.NAME_FILE);
		gs.read(FILES.GREET_FILE);
	});

	const greeting = $derived(gs.greet || 'Hello');
	const name = $derived(gs.name || 'World');
	const message = $derived(`${greeting}, ${name}!`);
</script>

<Card class="w-105 shadow-xl backdrop-blur-sm">
	<Header class="pt-6">
		<Title class="text-center text-3xl font-bold">
			{message}
		</Title>
	</Header>
	<Content class="p-6">
		<form onsubmit={handleSubmit} class="space-y-3">
			<div>
				<label for="greeting-input" class="text-sm font-medium">Greeting Phrase</label>
				<Input
					autocomplete="off"
					autocorrect="off"
					id="greeting-input"
					type="text"
					placeholder="e.g., Hello, Welcome"
					bind:value={gs.greet}
					class="mt-1"
				/>
			</div>
			<div>
				<label for="name-input" class="text-sm font-medium">Your Name</label>
				<Input
					autocomplete="off"
					autocorrect="off"
					id="name-input"
					type="text"
					placeholder="Enter your name"
					bind:value={gs.name}
					class="mt-1"
				/>
			</div>
			<div class="flex space-x-4">
				<Button type="submit" class="flex-1">Save</Button>
				<Button type="button" variant="outline" onclick={handleReset} class="flex-1">Reset</Button>
			</div>
		</form>
	</Content>
</Card>
