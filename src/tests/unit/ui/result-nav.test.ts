import { describe, expect, it } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/svelte';
import ResultNav from '$lib/components/ResultNav.svelte';

const sections = [
	{ id: 'rs-overview', label: 'Overview' },
	{ id: 'rs-advanced', label: 'Advanced' }
];

describe('ResultNav', () => {
	it('opens a collapsed <details> section when its link is clicked', async () => {
		document.body.innerHTML = '<details id="rs-advanced"><summary>Advanced</summary></details>';
		render(ResultNav, { sections });
		const el = document.getElementById('rs-advanced');
		expect(el).toBeInstanceOf(HTMLDetailsElement);
		expect((el as HTMLDetailsElement).open).toBe(false);

		await fireEvent.click(screen.getByRole('link', { name: 'Advanced' }));
		expect((el as HTMLDetailsElement).open).toBe(true);
		document.body.innerHTML = '';
	});

	it('positions below the sticky tab bar when asked', () => {
		render(ResultNav, { sections, stickyTopClass: 'top-11' });
		expect(screen.getByRole('navigation', { name: 'Result sections' }).className).toContain(
			'top-11'
		);
	});
});
