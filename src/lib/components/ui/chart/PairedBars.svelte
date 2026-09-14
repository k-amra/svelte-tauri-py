<script lang="ts">
	/**
	 * Side-by-side bar chart for a small, fixed number of slots (hours, weekdays).
	 *
	 * Each slot is absolutely positioned at `left: {i*step}%; width: {step}%`
	 * and contains two flex-1 bars (previous on the left, current on the right)
	 * when a previous series is present.
	 */
	interface Props {
		current: number[];
		previous?: number[] | null;
		labels?: string[] | null;
		format?: (v: number) => string;
		height?: number;
		currentClass?: string;
		previousClass?: string;
	}

	let {
		current,
		previous = null,
		labels = null,
		format = (v) => v.toLocaleString(),
		height = 64,
		currentClass = 'bg-teal-500',
		previousClass = 'bg-amber-500/60'
	}: Props = $props();

	const n = $derived(current.length);
	const step = $derived(n > 0 ? 100 / n : 0);

	const hasPrevious = $derived(
		previous != null && previous.length === current.length && current.length > 0
	);

	const maxValue = $derived.by(() => {
		const all = [...current, ...(hasPrevious ? (previous as number[]) : [])];
		return Math.max(1, ...all);
	});

	const slots = $derived.by(() =>
		current.map((c, i) => ({
			label: labels?.[i] ?? String(i),
			current: c,
			previousValue: hasPrevious ? (previous as number[])[i] : null,
			leftPct: i * step,
			widthPct: step,
			currentHeightPct: Math.max(2, (c / maxValue) * 100),
			previousHeightPct: hasPrevious ? Math.max(2, ((previous as number[])[i] / maxValue) * 100) : 0
		}))
	);

	function titleFor(s: { label: string; current: number; previousValue: number | null }): string {
		const parts = [s.label, format(s.current)];
		if (s.previousValue != null) parts.push(`prev: ${format(s.previousValue)}`);
		return parts.join(' — ');
	}
</script>

<div class="bg-muted relative overflow-hidden rounded" style="height: {height}px">
	{#each slots as s, i (i)}
		<div
			class="absolute bottom-0 flex items-end justify-around gap-px"
			style="left: {s.leftPct}%; width: {s.widthPct}%; height: 100%;"
			title={titleFor(s)}
		>
			{#if hasPrevious}
				<div class="flex-1 rounded-t {previousClass}" style="height: {s.previousHeightPct}%"></div>
				<div class="flex-1 rounded-t {currentClass}" style="height: {s.currentHeightPct}%"></div>
			{:else}
				<div class="flex-1 rounded-t {currentClass}" style="height: {s.currentHeightPct}%"></div>
			{/if}
		</div>
	{/each}
</div>
