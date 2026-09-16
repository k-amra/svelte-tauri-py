<script lang="ts">
	import { type ChatStatsResult, WEEKDAY_LABELS } from '$lib/api/chatStats';
	import OverlayBars from '$lib/components/ui/chart/OverlayBars.svelte';
	import PairedBars from '$lib/components/ui/chart/PairedBars.svelte';

	let { stats, anomalySigma }: { stats: ChatStatsResult; anomalySigma: number } = $props();

	const maxHeat = $derived(Math.max(1, ...stats.activity_by_weekday_hour.flat()));
	const maxNewChatter = $derived(
		stats.daily_new_chatters.length > 0
			? Math.max(...stats.daily_new_chatters.map((d) => d.count))
			: 1
	);
	const maxReturningChatter = $derived(
		stats.daily_returning_chatters.length > 0
			? Math.max(...stats.daily_returning_chatters.map((d) => d.count))
			: 1
	);
	const maxTrendCount = $derived(
		stats.trend_by_day.length > 0 ? Math.max(...stats.trend_by_day.map((p) => p.count)) : 1
	);
	const maxFirstHour = $derived(Math.max(1, ...stats.first_message_hours));
</script>

<div class="lg:col-span-2">
	<div class="border-border/60 mb-2 flex items-baseline justify-between border-b pb-1">
		<p class="text-sm font-medium">Activity by hour (UTC)</p>
		{#if stats.previous_period?.activity_by_hour?.length === 24}
			<span class="text-muted-foreground flex items-center gap-3 text-xs">
				<span class="flex items-center gap-1">
					<span class="size-2 rounded-sm bg-teal-500"></span>current
				</span>
				<span class="flex items-center gap-1">
					<span class="size-2 rounded-sm bg-amber-500/60"></span>previous
				</span>
			</span>
		{/if}
	</div>
	<PairedBars
		current={stats.activity_by_hour}
		previous={stats.previous_period?.activity_by_hour ?? null}
		labels={Array.from({ length: 24 }, (_, h) => `${h}:00`)}
		height={80}
		currentClass="bg-teal-500"
		previousClass="bg-amber-500/60"
	/>
</div>

<div class="lg:col-span-2">
	<p class="border-border/60 mb-2 border-b pb-1 text-sm font-medium">
		Weekday × hour heatmap (UTC)
	</p>
	<div class="grid gap-0.5" style="grid-template-columns: auto repeat(24, minmax(0, 1fr));">
		{#each stats.activity_by_weekday_hour as row, d (WEEKDAY_LABELS[d])}
			<span class="text-muted-foreground pr-1 text-right text-[10px]">{WEEKDAY_LABELS[d]}</span>
			{#each row as count, h (`${d}-${h}`)}
				<div
					class="aspect-square rounded-[2px] bg-teal-500"
					style="opacity: {count === 0 ? 0.08 : 0.15 + 0.85 * (count / maxHeat)}"
					title="{WEEKDAY_LABELS[d]} {h}:00 — {count}"
				></div>
			{/each}
		{/each}
	</div>
	<div class="text-muted-foreground mt-2 flex items-center gap-2 text-[10px]">
		<span>0</span>
		<div
			class="h-2 w-24 rounded-sm"
			style="background: linear-gradient(to right, rgba(20, 184, 166, 0.08), rgb(20, 184, 166))"
		></div>
		<span>{maxHeat.toLocaleString()} msgs</span>
	</div>
</div>

<div class="lg:col-span-2">
	<div class="border-border/60 mb-2 flex items-baseline justify-between border-b pb-1">
		<p class="text-sm font-medium">Messages per day</p>
		{#if stats.previous_period?.messages_per_day?.length === stats.messages_per_day.length}
			<span class="text-muted-foreground flex items-center gap-3 text-xs">
				<span class="flex items-center gap-1">
					<span class="size-2 rounded-sm bg-teal-500"></span>current
				</span>
				<span class="flex items-center gap-1">
					<span class="size-2 rounded-full border-[1.5px] border-amber-500"></span>previous
				</span>
			</span>
		{/if}
	</div>
	<OverlayBars
		current={stats.messages_per_day.map((d) => d.count)}
		previous={stats.previous_period?.messages_per_day?.map((d) => d.count) ?? null}
		dates={stats.messages_per_day.map((d) => d.date)}
		height={64}
		barClass="bg-teal-500"
		lineClass="text-amber-500"
	/>
</div>

{#if stats.daily_new_chatters.length > 0 || stats.daily_returning_chatters.length > 0}
	<div class="lg:col-span-2">
		<p class="border-border/60 mb-2 border-b pb-1 text-sm font-medium">
			New vs returning chatters (per day)
		</p>
		<div class="space-y-2">
			{#if stats.daily_new_chatters.length > 0}
				<div>
					<p class="text-muted-foreground text-xs">New</p>
					<div class="bg-muted flex h-10 items-end gap-0.5 overflow-x-auto rounded p-1">
						{#each stats.daily_new_chatters as day (day.date)}
							<div
								class="min-w-1.5 flex-1 rounded-t bg-emerald-500"
								style="height: {Math.max(3, (day.count / maxNewChatter) * 100)}%"
								title="{day.date} — {day.count} new"
							></div>
						{/each}
					</div>
				</div>
			{/if}
			{#if stats.daily_returning_chatters.length > 0}
				<div>
					<p class="text-muted-foreground text-xs">Returning</p>
					<div class="bg-muted flex h-10 items-end gap-0.5 overflow-x-auto rounded p-1">
						{#each stats.daily_returning_chatters as day (day.date)}
							<div
								class="min-w-1.5 flex-1 rounded-t bg-sky-500"
								style="height: {Math.max(3, (day.count / maxReturningChatter) * 100)}%"
								title="{day.date} — {day.count} returning"
							></div>
						{/each}
					</div>
				</div>
			{/if}
		</div>
	</div>
{/if}

{#if stats.weekly_seasonality}
	<div>
		<p class="border-border/60 mb-2 border-b pb-1 text-sm font-medium">
			Weekly seasonality (vs trend)
		</p>
		<div class="grid grid-cols-7 gap-0.5">
			{#each stats.weekly_seasonality as mult, d (WEEKDAY_LABELS[d])}
				<div
					class="rounded p-1 text-center text-[10px] {mult >= 1
						? 'bg-green-500/70'
						: 'bg-red-500/70'}"
					style="opacity: {0.25 + 0.75 * Math.min(1, Math.abs(1 - mult) * 4)}"
					title="{WEEKDAY_LABELS[d]}: {mult}× trend"
				>
					{WEEKDAY_LABELS[d]}
				</div>
			{/each}
		</div>
	</div>
{/if}

{#if stats.trend_by_day.length > 0}
	<div class="lg:col-span-2">
		<p class="border-border/60 mb-2 border-b pb-1 text-sm font-medium">
			Trend (7-day centered moving average)
		</p>
		<div class="bg-muted flex h-16 items-end gap-0.5 overflow-x-auto rounded p-1">
			{#each stats.trend_by_day as p (p.date)}
				<div
					class="min-w-1.5 flex-1 rounded-t bg-amber-500"
					style="height: {Math.max(3, (p.count / maxTrendCount) * 100)}%"
					title="{p.date} — trend {p.count.toFixed(1)}"
				></div>
			{/each}
		</div>
	</div>
{/if}

{#if stats.top_peaks_5m.length > 0}
	<div>
		<p class="border-border/60 mb-2 border-b pb-1 text-sm font-medium">Peak 5-minute windows</p>
		<ul class="text-xs">
			{#each stats.top_peaks_5m as peak (peak.window_start)}
				<li>{new Date(peak.window_start).toLocaleString()} — {peak.message_count} msgs</li>
			{/each}
		</ul>
	</div>
{/if}

<div class="lg:col-span-2">
	<p class="border-border/60 mb-2 border-b pb-1 text-sm font-medium">
		First message by hour (UTC, in-range first seen)
	</p>
	<div class="flex h-20 items-end gap-0.5">
		{#each stats.first_message_hours as count, h (h)}
			<div
				class="flex-1 rounded-t bg-teal-500"
				style="height: {Math.max(2, (count / maxFirstHour) * 100)}%"
				title="{h}:00 — {count}"
			></div>
		{/each}
	</div>
</div>

{#if stats.sessions.total_sessions > 0}
	<div class="text-xs">
		<p class="border-border/60 mb-2 border-b pb-1 text-sm font-medium">Sessions</p>
		<dl class="grid grid-cols-3 gap-x-4 gap-y-1">
			<div>
				<dt class="text-muted-foreground">Total</dt>
				<dd class="tabular-nums">{stats.sessions.total_sessions.toLocaleString()}</dd>
			</div>
			<div>
				<dt class="text-muted-foreground">Avg msgs</dt>
				<dd class="tabular-nums">{stats.sessions.avg_messages_per_session?.toFixed(1) ?? '—'}</dd>
			</div>
			<div>
				<dt class="text-muted-foreground">Avg min</dt>
				<dd class="tabular-nums">{stats.sessions.avg_session_minutes?.toFixed(1) ?? '—'}</dd>
			</div>
			<div>
				<dt class="text-muted-foreground">Median min</dt>
				<dd class="tabular-nums">{stats.sessions.median_session_minutes?.toFixed(1) ?? '—'}</dd>
			</div>
			<div>
				<dt class="text-muted-foreground">p90 min</dt>
				<dd class="tabular-nums">{stats.sessions.p90_session_minutes?.toFixed(1) ?? '—'}</dd>
			</div>
			<div>
				<dt class="text-muted-foreground">Longest min</dt>
				<dd class="tabular-nums">{stats.sessions.longest_session_minutes?.toFixed(1) ?? '—'}</dd>
			</div>
		</dl>
	</div>
{/if}

{#if stats.anomalies_5m.length > 0}
	<div>
		<div class="border-border/60 mb-2 flex items-baseline justify-between border-b pb-1">
			<p class="text-sm font-medium">Anomalies (5m)</p>
			<span class="text-muted-foreground text-xs">z ≥ {anomalySigma}</span>
		</div>
		<ul class="text-xs">
			{#each stats.anomalies_5m.slice(0, 10) as a (a.window_start)}
				<li>
					{new Date(a.window_start).toLocaleString()} — {a.message_count} msgs (z {a.z_score}, p {a.p_value})
				</li>
			{/each}
		</ul>
	</div>
{/if}
