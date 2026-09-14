import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/svelte';
import ResultNav from '$lib/components/ResultNav.svelte';

const sections = [
	{ id: 'rs-overview', label: 'Overview' },
	{ id: 'rs-advanced', label: 'Advanced' }
];

describe('ResultNav', () => {
	it('positions below the sticky tab bar when asked', () => {
		render(ResultNav, { sections, stickyTopClass: 'top-11' });
		expect(screen.getByRole('navigation', { name: 'Result sections' }).className).toContain(
			'top-11'
		);
	});
});
