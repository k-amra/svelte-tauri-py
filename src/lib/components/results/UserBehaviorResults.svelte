<script lang="ts">
	import type { ChatStatsResult } from '$lib/api/chatStats';

	let { stats, isPerUser }: { stats: ChatStatsResult; isPerUser: boolean } = $props();

	const maxStaff = $derived(
		stats.staff_list.length > 0 ? Math.max(...stats.staff_list.map((s) => s.messageCount)) : 1
	);
	const maxSubscriber = $derived(
		stats.subscriber_list.length > 0
			? Math.max(...stats.subscriber_list.map((s) => s.messageCount))
			: 1
	);
	const maxCohortOffset = $derived(
		stats.cohort_retention.length > 0
			? Math.max(...stats.cohort_retention.flatMap((r) => r.retention.map((c) => c.week_offset)))
			: 0
	);
</script>

{#if stats.roles.length > 0}
	<div>
		<p class="border-border/60 mb-2 border-b pb-1 text-sm font-medium">Roles</p>
		<ul class="grid grid-cols-2 gap-1 text-xs">
			{#each stats.roles as role (role.role)}
				<li class="bg-muted rounded px-2 py-1">
					{role.role}: {role.messages.toLocaleString()} msgs · {role.unique_users.toLocaleString()}
					users
				</li>
			{/each}
		</ul>
	</div>
{/if}

{#if !isPerUser && stats.staff_list.length > 0}
	<div>
		<div class="border-border/60 mb-2 flex items-baseline justify-between border-b pb-1">
			<p class="text-sm font-medium">Moderators &amp; VIPs</p>
			<span class="text-muted-foreground text-xs">{stats.staff_list.length} staff</span>
		</div>
		<div class="space-y-1">
			{#each stats.staff_list as s (s.user_id)}
				<div class="flex items-center gap-2 text-xs">
					<span
						class="w-24 truncate"
						title="{s.username} · {s.role}{s.firstSeen
							? ` · first ${new Date(s.firstSeen).toLocaleDateString()}`
							: ''}">{s.username}</span
					>
					<span class="text-muted-foreground w-20 shrink-0 text-[10px] uppercase">{s.role}</span>
					<div class="bg-muted h-3 flex-1 overflow-hidden rounded-full">
						<div
							class="h-full rounded-full bg-cyan-500 transition-[width] duration-300"
							style="width: {(s.messageCount / maxStaff) * 100}%"
						></div>
					</div>
					<span class="w-12 text-right">{s.messageCount.toLocaleString()}</span>
				</div>
			{/each}
		</div>
	</div>
{/if}

{#if !isPerUser && stats.subscriber_list.length > 0}
	<div>
		<div class="border-border/60 mb-2 flex items-baseline justify-between border-b pb-1">
			<p class="text-sm font-medium">Subscribers</p>
			<span class="text-muted-foreground text-xs">
				{stats.subscriber_list.length} of {stats.subscriber_count}
			</span>
		</div>
		<div class="space-y-1">
			{#each stats.subscriber_list as s (s.user_id)}
				<div class="flex items-center gap-2 text-xs">
					<span
						class="w-24 truncate"
						title="{s.username}{s.firstSeen
							? ` · first ${new Date(s.firstSeen).toLocaleDateString()}`
							: ''}">{s.username}</span
					>
					<div class="bg-muted h-3 flex-1 overflow-hidden rounded-full">
						<div
							class="h-full rounded-full bg-fuchsia-500 transition-[width] duration-300"
							style="width: {(s.messageCount / maxSubscriber) * 100}%"
						></div>
					</div>
					<span class="w-12 text-right">{s.messageCount.toLocaleString()}</span>
				</div>
			{/each}
		</div>
	</div>
{/if}

{#if !isPerUser && stats.concentration.gini_coefficient != null}
	<div class="text-xs">
		<p class="border-border/60 mb-2 border-b pb-1 text-sm font-medium">Concentration</p>
		<p class="text-muted-foreground">
			Gini {stats.concentration.gini_coefficient} · top 10% share {stats.concentration
				.top_10pct_share}%
		</p>
	</div>
{/if}

<div class="text-xs">
	<p class="border-border/60 mb-2 border-b pb-1 text-sm font-medium">Message classes</p>
	<p class="text-muted-foreground">
		? {stats.message_classes.questions.toLocaleString()} · !
		{stats.message_classes.exclamations.toLocaleString()} · CAPS
		{stats.message_classes.all_caps.toLocaleString()} · emote-only
		{stats.message_classes.emote_only.toLocaleString()} · short
		{stats.message_classes.short_messages.toLocaleString()} · long
		{stats.message_classes.long_messages.toLocaleString()}
	</p>
	<p class="text-muted-foreground">
		self-repeats {stats.self_repetition_count.toLocaleString()}{stats.self_repetition_pct != null
			? ` (${stats.self_repetition_pct}%)`
			: ''} · non-ASCII {stats.messages_with_non_ascii.toLocaleString()}{stats.non_ascii_ratio !=
		null
			? ` (${(stats.non_ascii_ratio * 100).toFixed(1)}% of chars)`
			: ''}
	</p>
</div>

{#if !isPerUser && stats.lorenz_samples.length > 0}
	<div>
		<p class="border-border/60 mb-2 border-b pb-1 text-sm font-medium">
			Lorenz curve (message share by top %)
		</p>
		<ul class="text-xs">
			{#each stats.lorenz_samples as s (s.top_pct)}
				<li>top {s.top_pct}% → {s.message_share_pct}% of messages</li>
			{/each}
		</ul>
	</div>
{/if}

{#if stats.cohort_retention.length > 0}
	<div class="lg:col-span-2">
		<p class="border-border/60 mb-2 border-b pb-1 text-sm font-medium">
			Weekly cohort retention (%)
		</p>
		<div class="overflow-x-auto">
			<table class="text-[10px]">
				<thead>
					<tr class="text-muted-foreground">
						<th class="pr-2 text-left font-medium">Cohort</th>
						<th class="pr-2 text-right font-medium">Size</th>
						{#each Array.from({ length: maxCohortOffset + 1 }, (_, i) => i) as w (w)}
							<th class="pr-2 text-right font-medium">W{w}</th>
						{/each}
					</tr>
				</thead>
				<tbody>
					{#each stats.cohort_retention as row (row.cohort_week)}
						<tr>
							<td class="pr-2">{row.cohort_week}</td>
							<td class="pr-2 text-right">{row.cohort_size}</td>
							{#each Array.from({ length: maxCohortOffset + 1 }, (_, i) => i) as w (w)}
								{@const cell = row.retention.find((c) => c.week_offset === w)}
								<td
									class="pr-2 text-right"
									style="opacity: {cell ? 0.3 + 0.7 * (cell.retention_pct / 100) : 0.2}"
								>
									{cell ? cell.retention_pct.toFixed(0) : '—'}
								</td>
							{/each}
						</tr>
					{/each}
				</tbody>
			</table>
		</div>
	</div>
{/if}
