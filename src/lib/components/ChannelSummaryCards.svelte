<script lang="ts">
	import type { ChannelSummary } from '$lib/api/chatStats';

	let {
		summaries,
		onDrillChannel
	}: {
		summaries: ChannelSummary[];
		onDrillChannel?: (channel: string) => void;
	} = $props();

	// Calculate the pooled total across all channels to provide accurate "share of total" context
	const totalMessagesAllChannels = $derived(
		summaries.reduce((acc, s) => acc + s.total_messages, 0)
	);
</script>

<div class="space-y-4 lg:col-span-2">
	<div class="border-border/60 flex items-baseline justify-between border-b pb-1">
		<div>
			<p class="text-sm font-medium">Per-channel breakdown</p>
			<p class="text-muted-foreground text-xs">
				{summaries.length} channels · pooled totals above, splits below
			</p>
		</div>
		<p class="text-muted-foreground text-xs font-medium">
			{totalMessagesAllChannels.toLocaleString()} total messages
		</p>
	</div>

	<div class="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
		{#each summaries as s (s.channel)}
			{@const share =
				totalMessagesAllChannels > 0 ? (s.total_messages / totalMessagesAllChannels) * 100 : 0}
			{@const msgsPerChatter =
				s.unique_chatters > 0 ? (s.total_messages / s.unique_chatters).toFixed(1) : '—'}
			{@const maxChatterInChannel =
				s.top_chatters.length > 0 ? Math.max(...s.top_chatters.map((c) => c.messageCount)) : 1}
			{@const maxEmoteInChannel =
				s.top_emotes.length > 0 ? Math.max(...s.top_emotes.map((e) => e.count)) : 1}

			<div class="bg-muted/40 border-border/60 flex flex-col rounded-lg border p-3">
				<!-- Header -->
				<div class="mb-3 flex items-center justify-between">
					<button
						type="button"
						class="hover:text-primary truncate text-left text-sm font-medium hover:underline"
						title={onDrillChannel
							? `${s.channel} — click to scope all stats to this channel`
							: s.channel}
						disabled={!onDrillChannel}
						onclick={() => onDrillChannel?.(s.channel)}
					>
						{s.channel}
					</button>
					<span
						class="bg-primary/10 text-primary rounded-full px-1.5 py-0.5 text-[10px] font-medium"
					>
						{share.toFixed(1)}% of total
					</span>
				</div>

				<!-- Big Stats -->
				<div class="mb-3 grid grid-cols-3 gap-1 text-center text-xs">
					<div>
						<div class="text-base font-semibold tabular-nums">
							{s.total_messages.toLocaleString()}
						</div>
						<div class="text-muted-foreground text-[10px] uppercase">messages</div>
					</div>
					<div>
						<div class="text-base font-semibold tabular-nums">
							{s.unique_chatters.toLocaleString()}
						</div>
						<div class="text-muted-foreground text-[10px] uppercase">chatters</div>
					</div>
					<div>
						<div class="text-base font-semibold tabular-nums">{msgsPerChatter}</div>
						<div class="text-muted-foreground text-[10px] uppercase">msgs/chatter</div>
					</div>
				</div>

				<!-- Progress Bar (Share of Total) -->
				<div class="mb-4">
					<div class="bg-muted flex h-1.5 overflow-hidden rounded-full">
						<div
							class="h-full rounded-full bg-teal-500 transition-[width] duration-300"
							style="width: {share}%"
							title="{s.total_messages.toLocaleString()} messages ({share.toFixed(1)}% of total)"
						></div>
					</div>
				</div>

				<!-- Lists -->
				<div class="flex-1 space-y-3">
					{#if s.top_chatters.length > 0}
						<div>
							<p class="text-muted-foreground mb-1.5 text-[10px] uppercase">Top chatters</p>
							<ul class="space-y-1.5 text-xs">
								{#each s.top_chatters.slice(0, 3) as c (c.user_id)}
									<li class="flex items-center gap-2">
										<span class="w-20 truncate" title={c.username}>{c.username}</span>
										<div class="bg-muted h-1.5 flex-1 overflow-hidden rounded-full">
											<div
												class="h-full rounded-full bg-teal-500/70"
												style="width: {(c.messageCount / maxChatterInChannel) * 100}%"
											></div>
										</div>
										<span class="text-muted-foreground w-10 text-right tabular-nums">
											{c.messageCount.toLocaleString()}
										</span>
									</li>
								{/each}
							</ul>
						</div>
					{/if}

					{#if s.top_emotes.length > 0}
						<div>
							<p class="text-muted-foreground mb-1.5 text-[10px] uppercase">Top emotes</p>
							<ul class="space-y-1.5 text-xs">
								{#each s.top_emotes.slice(0, 3) as e (e.name)}
									<li class="flex items-center gap-2">
										<span class="w-20 truncate" title={e.name}>{e.name}</span>
										<div class="bg-muted h-1.5 flex-1 overflow-hidden rounded-full">
											<div
												class="h-full rounded-full bg-purple-500/70"
												style="width: {(e.count / maxEmoteInChannel) * 100}%"
											></div>
										</div>
										<span class="text-muted-foreground w-10 text-right tabular-nums">
											{e.count.toLocaleString()}
										</span>
									</li>
								{/each}
							</ul>
						</div>
					{/if}
				</div>
			</div>
		{/each}
	</div>
</div>
