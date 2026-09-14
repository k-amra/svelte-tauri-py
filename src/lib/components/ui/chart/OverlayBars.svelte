<script lang="ts">
	/**
	 * Bar chart with an optional overlaid polyline for a comparison series.
	 *
	 * Bars are absolutely positioned at `left: {i*step}%; width: {step}%` so
	 * their centers land at exactly `(i + 0.5) * step` — the same coordinate
	 * the SVG polyline uses inside its `viewBox="0 0 100 100"`. That keeps the
	 * line locked to bar midpoints regardless of container width.
	 *
	 * When the previous series has a different length than the current one,
	 * the overlay is dropped (misaligned comparison is worse than none).
	 */
	interface Props {
		current: number[];
		previous?: number[] | null;
		dates?: string[] | null;
		format?: (v: number) => string;
		height?: number;
		barClass?: string;
		lineClass?: string;
	}

	let {
		current,
		previous = null,
		dates = null,
		format = (v) => v.toLocaleString(),
		height = 64,
		barClass = 'bg-teal-500',
		lineClass = 'text-amber-500'
	}: Props = $props();

	const n = $derived(current.length);
	const step = $derived(n > 0 ? 100 / n : 0);
	// Each side of a bar's horizontal breathing room, as % of container width.
	// Small enough that the polyline still reads as touching the bars.
	const gapHalf = 0.15;

	const hasOverlay = $derived(
		previous != null && previous.length === current.length && current.length > 0
	);

	const maxValue = $derived.by(() => {
		const all = [...current, ...(hasOverlay ? (previous as number[]) : [])];
		return Math.max(1, ...all);
	});

	const bars = $derived.by(() =>
		current.map((v, i) => ({
			value: v,
			date: dates?.[i] ?? null,
			previousValue: hasOverlay ? (previous as number[])[i] : null,
			leftPct: i * step + gapHalf,
			widthPct: Math.max(0.05, step - 2 * gapHalf),
			heightPct: Math.max(2, (v / maxValue) * 100)
		}))
	);

	const polyline = $derived.by(() => {
		if (!hasOverlay) return '';
		return (previous as number[])
			.map((v, i) => {
				const x = (i + 0.5) * step;
				const y = 100 - (v / maxValue) * 100;
				return `${x.toFixed(3)},${y.toFixed(3)}`;
			})
			.join(' ');
	});

	function titleFor(b: {
		value: number;
		date: string | null;
		previousValue: number | null;
	}): string {
		const parts: string[] = [];
		if (b.date) parts.push(b.date);
		parts.push(format(b.value));
		if (b.previousValue != null) parts.push(`prev: ${format(b.previousValue)}`);
		return parts.join(' — ');
	}
</script>

<div class="bg-muted relative overflow-hidden rounded" style="height: {height}px">
	{#each bars as b, i (i)}
		<div
			class="absolute bottom-0 rounded-t {barClass}"
			style="left: {b.leftPct}%; width: {b.widthPct}%; height: {b.heightPct}%;"
			title={titleFor(b)}
		></div>
	{/each}

	{#if hasOverlay}
		<svg
			class="pointer-events-none absolute inset-0 h-full w-full"
			viewBox="0 0 100 100"
			preserveAspectRatio="none"
			aria-hidden="true"
		>
			<polyline
				points={polyline}
				fill="none"
				class={lineClass}
				stroke="currentColor"
				stroke-width="1.5"
				stroke-linejoin="round"
				stroke-linecap="round"
				vector-effect="non-scaling-stroke"
			/>
		</svg>
	{/if}
</div>
