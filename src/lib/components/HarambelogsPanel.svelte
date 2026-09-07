<script lang="ts">
	import { api } from '$lib/api/client';
	import { backend } from '$lib/api/backend.svelte';
	import type { FullMessage } from '$lib/api/harambelogs';
	import { Button } from '$lib/components/ui/button/index';
	import { Input } from '$lib/components/ui/input/index';
	import { Card, Header, Title, Content } from '$lib/components/ui/card/index';

	let channel = $state('xqc');
	let user = $state('xqc');
	let query = $state('');
	let loading = $state(false);
	let error = $state('');
	let messages = $state<FullMessage[]>([]);

	async function search() {
		const trimmedQuery = query.trim();
		if (!trimmedQuery || loading) return;

		loading = true;
		error = '';
		messages = [];

		try {
			const res = await api.harambelogs.search(
				'channel', // cType: ChannelIdType
				channel, 
				'user',    // uType: UserIdType
				user, 
				trimmedQuery
			);
			
			messages = res.messages;
			if (messages.length === 0) error = 'No messages found matching your query.';
		} catch (e) {
			error = e instanceof Error ? e.message : String(e);
		} finally {
			loading = false;
		}
	}
</script>

<Card class="w-105 shadow-xl backdrop-blur-sm">
	<Header class="pt-6">
		<Title class="text-center text-2xl font-bold">Harambelogs Search</Title>
		<p class="text-muted-foreground text-center text-sm">Query Twitch chat logs</p>
	</Header>
	<Content class="space-y-3 p-6">
		<div class="grid grid-cols-2 gap-3">
			<div>
				<label for="hl-channel" class="text-sm font-medium">Channel</label>
				<Input id="hl-channel" bind:value={channel} class="mt-1" autocomplete="off" />
			</div>
			<div>
				<label for="hl-user" class="text-sm font-medium">User</label>
				<Input id="hl-user" bind:value={user} class="mt-1" autocomplete="off" />
			</div>
		</div>

		<div>
			<label for="hl-query" class="text-sm font-medium">Search Query</label>
			<Input
				id="hl-query"
				bind:value={query}
				class="mt-1"
				placeholder="e.g. LULW, copium"
				autocomplete="off"
				onkeydown={(event) => {
					if (event.key === 'Enter') void search();
				}}
			/>
		</div>

		<Button
			onclick={search}
			disabled={loading || !backend.ready}
			class="w-full bg-linear-to-r from-indigo-500 to-pink-500"
		>
			{loading ? 'Searching…' : 'Search Logs'}
		</Button>

		{#if error}
			<p class="text-center text-sm text-red-500">{error}</p>
		{/if}

		{#if messages.length > 0}
			<div
				class="bg-muted border-border/50 max-h-60 space-y-2 overflow-auto rounded border p-3 text-xs"
			>
				{#each messages as msg (msg.id)}
					<div class="border-border/30 border-b pb-1 last:border-0">
						<div class="flex items-baseline justify-between">
							<span class="text-primary font-bold">{msg.displayName}</span>
							<span class="text-muted-foreground text-[10px]">
								{new Date(msg.timestamp).toLocaleString()}
							</span>
						</div>
						<p class="mt-0.5 break-words">{msg.text}</p>
					</div>
				{/each}
			</div>
		{/if}
	</Content>
</Card>