/**
 * Shared delta helpers used by tile headers and the comparison section.
 *
 * `direction` matters for coloring: "higher-is-better" turns a positive delta
 * green, "lower-is-better" turns it red, "neutral" leaves it muted. Zero-baseline
 * cases ("new", "gone") get their tone from the direction too.
 */
export type Direction = 'higher-is-better' | 'lower-is-better' | 'neutral';
export type DeltaTone = 'good' | 'bad' | 'flat';
export type Format = 'int' | 'float1' | 'float3' | 'percent';

export interface Delta {
	text: string;
	tone: DeltaTone;
	previousText: string;
}

export function formatValue(value: number, format: Format): string {
	if (format === 'float1') return value.toFixed(1);
	if (format === 'float3') return value.toFixed(3);
	if (format === 'percent') return `${(value * 100).toFixed(1)}%`;
	return value.toLocaleString();
}

export function computeDelta(
	current: number | null | undefined,
	previous: number | null | undefined,
	direction: Direction,
	format: Format = 'int'
): Delta | null {
	if (current == null || previous == null) return null;
	const previousText = formatValue(previous, format);

	if (previous === 0 && current === 0) {
		return { text: '±0', tone: 'flat', previousText };
	}
	if (previous === 0) {
		return {
			text: 'new',
			tone: direction === 'lower-is-better' ? 'bad' : 'good',
			previousText
		};
	}
	if (current === 0) {
		return {
			text: 'gone',
			tone: direction === 'lower-is-better' ? 'good' : 'bad',
			previousText
		};
	}
	if (current === previous) {
		return { text: '±0', tone: 'flat', previousText };
	}

	const pct = ((current - previous) / previous) * 100;
	const arrow = pct > 0 ? '▲' : '▼';
	const tone: DeltaTone =
		direction === 'neutral'
			? 'flat'
			: pct > 0 === (direction === 'higher-is-better')
				? 'good'
				: 'bad';
	return {
		text: `${arrow} ${Math.abs(pct).toFixed(1)}%`,
		tone,
		previousText
	};
}
