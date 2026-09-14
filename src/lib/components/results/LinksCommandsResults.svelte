<script lang="ts">
	import type { ChannelSummary, ChatStatsResult } from '$lib/api/chatStats';
	import SplitByChannel from '$lib/components/results/SplitByChannel.svelte';
	import PerChannelCommands from '$lib/components/results/PerChannelCommands.svelte';
	import PerChannelDomains from '$lib/components/results/PerChannelDomains.svelte';
	import PerChannelMentions from '$lib/components/results/PerChannelMentions.svelte';

	let {
		stats,
		summaries = []
	}: {
		stats: ChatStatsResult;
		summaries?: ChannelSummary[];
	} = $props();

	const isMultiChannel = $derived(summaries.length > 1);

	const maxCommand = $derived(
		stats.top_commands.length > 0 ? Math.max(...stats.top_commands.map((c) => c.count)) : 1
	);
	const maxDomain = $derived(
		stats.top_domains.length > 0 ? Math.max(...stats.top_domains.map((d) => d.count)) : 1
	);
	const maxMention = $derived(
		stats.top_mentions.length > 0 ? Math.max(...stats.top_mentions.map((m) => m.count)) : 1
	);
	const maxRepeated = $derived(
		stats.top_repeated_messages.length > 0
			? Math.max(...stats.top_repeated_messages.map((r) => r.count))
			: 1
	);
	const maxCopyPaste = $derived(
		stats.top_copy_paste_chains.length > 0
			? Math.max(...stats.top_copy_paste_chains.map((c) => c.occurrences))
			: 1
	);
</script>

{#if isMultiChannel}
	<SplitByChannel {summaries} title="Top commands (per channel)" row={PerChannelCommands} />
{:else if stats.top_commands.length > 0}
	<div>
		<div class="border-border/60 mb-2 flex items-baseline justify-between border-b pb-1">
			<p class="text-sm font-medium">Top commands</p>
			<span class="text-muted-foreground text-xs">{stats.messages_with_commands} msgs</span>
		</div>
		<div class="space-y-1">
			{#each stats.top_commands as c (c.name)}
				<div class="flex items-center gap-2 text-xs">
					<span class="w-24 truncate">!{c.name}</span>
					<div class="bg-muted h-3 flex-1 overflow-hidden rounded-full">
						<div
							class="h-full rounded-full bg-amber-500 transition-[width] duration-300"
							style="width: {(c.count / maxCommand) * 100}%"
						></div>
					</div>
					<span class="w-12 text-right">{c.count.toLocaleString()}</span>
				</div>
			{/each}
		</div>
	</div>
{/if}

{#if isMultiChannel}
	<SplitByChannel {summaries} title="Top link domains (per channel)" row={PerChannelDomains} />
{:else if stats.top_domains.length > 0}
	<div>
		<div class="border-border/60 mb-2 flex items-baseline justify-between border-b pb-1">
			<p class="text-sm font-medium">Top link domains</p>
			<span class="text-muted-foreground text-xs">{stats.messages_with_links} msgs</span>
		</div>
		<div class="space-y-1">
			{#each stats.top_domains as d (d.domain)}
				<div class="flex items-center gap-2 text-xs">
					<span class="w-24 truncate">{d.domain}</span>
					<div class="bg-muted h-3 flex-1 overflow-hidden rounded-full">
						<div
							class="h-full rounded-full bg-sky-500 transition-[width] duration-300"
							style="width: {(d.count / maxDomain) * 100}%"
						></div>
					</div>
					<span class="w-12 text-right">{d.count.toLocaleString()}</span>
				</div>
			{/each}
		</div>
		<p class="text-muted-foreground mt-1 text-xs">
			Clips {stats.platform_links.twitch_clips} · YouTube {stats.platform_links.youtube} · Discord
			{stats.platform_links.discord} · X {stats.platform_links.x_twitter} · Kick {stats
				.platform_links.kick} · Other {stats.platform_links.other}
		</p>
	</div>
{/if}

{#if isMultiChannel}
	<SplitByChannel {summaries} title="Top mentions (per channel)" row={PerChannelMentions} />
{:else if stats.top_mentions.length > 0}
	<div>
		<div class="border-border/60 mb-2 flex items-baseline justify-between border-b pb-1">
			<p class="text-sm font-medium">Top mentions</p>
			<span class="text-muted-foreground text-xs">{stats.messages_with_mentions} msgs</span>
		</div>
		<div class="space-y-1">
			{#each stats.top_mentions as m (m.username)}
				<div class="flex items-center gap-2 text-xs">
					<span class="w-24 truncate">@{m.username}</span>
					<div class="bg-muted h-3 flex-1 overflow-hidden rounded-full">
						<div
							class="h-full rounded-full bg-emerald-500 transition-[width] duration-300"
							style="width: {(m.count / maxMention) * 100}%"
						></div>
					</div>
					<span class="w-12 text-right">{m.count.toLocaleString()}</span>
				</div>
			{/each}
		</div>
		{#if stats.top_mention_pairs.length > 0}
			<ul class="text-muted-foreground mt-1 space-y-0.5 text-xs">
				{#each stats.top_mention_pairs.slice(0, 5) as pair (`${pair.from_user}-${pair.to_user}`)}
					<li>{pair.from_user} → {pair.to_user}: {pair.count}</li>
				{/each}
			</ul>
		{/if}
	</div>
{/if}

{#if stats.top_repeated_messages.length > 0}
	<div>
		<div class="border-border/60 mb-2 flex items-baseline justify-between border-b pb-1">
			<p class="text-sm font-medium">Repeated messages</p>
			<span class="text-muted-foreground text-xs">{stats.duplicate_message_count} dupes</span>
		</div>
		<div class="space-y-1">
			{#each stats.top_repeated_messages.slice(0, 10) as r (r.text)}
				<div class="flex items-center gap-2 text-xs">
					<span class="flex-1 truncate" title={r.text}>{r.text}</span>
					<div class="bg-muted h-3 w-24 overflow-hidden rounded-full">
						<div
							class="h-full rounded-full bg-rose-500 transition-[width] duration-300"
							style="width: {(r.count / maxRepeated) * 100}%"
						></div>
					</div>
					<span class="w-12 text-right">{r.count.toLocaleString()}</span>
				</div>
			{/each}
		</div>
	</div>
{/if}

{#if stats.top_copy_paste_chains.length > 0}
	<div>
		<div class="border-border/60 mb-2 flex items-baseline justify-between border-b pb-1">
			<p class="text-sm font-medium">Copy-paste chains</p>
			<span class="text-muted-foreground text-xs">
				{stats.cross_user_copy_paste_count} reposts / {stats.cross_user_copy_paste_texts} texts
			</span>
		</div>
		<div class="space-y-1">
			{#each stats.top_copy_paste_chains as c (c.text)}
				<div class="flex items-center gap-2 text-xs">
					<span class="flex-1 truncate" title={c.text}
						>{c.text}
						<span class="text-muted-foreground">· {c.distinct_users} users</span></span
					>
					<div class="bg-muted h-3 w-24 overflow-hidden rounded-full">
						<div
							class="h-full rounded-full bg-rose-500 transition-[width] duration-300"
							style="width: {(c.occurrences / maxCopyPaste) * 100}%"
						></div>
					</div>
					<span class="w-12 text-right">{c.occurrences.toLocaleString()}</span>
				</div>
			{/each}
		</div>
	</div>
{/if}

{#if stats.language_breakdown.length > 0}
	<div>
		<p class="border-border/60 mb-2 border-b pb-1 text-sm font-medium">Language</p>
		<ul class="text-xs">
			{#each stats.language_breakdown as l (l.language)}
				<li>{l.language}: {l.percentage}%</li>
			{/each}
		</ul>
	</div>
{/if}

{#if stats.language_by_day.length > 0}
	<div>
		<p class="border-border/60 mb-2 border-b pb-1 text-sm font-medium">Top language per day</p>
		<ul class="text-xs">
			{#each stats.language_by_day as d (d.date)}
				<li>{d.date} — {d.language} ({d.percentage}%)</li>
			{/each}
		</ul>
	</div>
{/if}
