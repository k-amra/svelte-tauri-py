import { describe, it, expect } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/svelte';
import App from '../../../App.svelte';
import { views, DEFAULT_VIEW } from '$lib/views';

// ---------------------------------------------------------------------------
// Tests: App shell (view registry + sidebar nav)
// Protects against: nav/view drift when adding views, broken default view
// ---------------------------------------------------------------------------

describe('view registry', () => {
	it('has unique ids and a valid default view', () => {
		const ids = views.map((v) => v.id);
		expect(new Set(ids).size).toBe(ids.length);
		expect(ids).toContain(DEFAULT_VIEW);
	});

	it('every view has a label and a component', () => {
		for (const v of views) {
			expect(v.label.length).toBeGreaterThan(0);
			expect(v.component).toBeTruthy();
			expect(v.icon).toBeTruthy();
		}
	});
});

describe('App shell', () => {
	it('shows the nav and the default view on startup', () => {
		render(App);
		expect(screen.getByRole('navigation', { name: 'Views' })).toBeInTheDocument();
		for (const v of views) {
			expect(screen.getByRole('button', { name: v.label })).toBeInTheDocument();
		}
		// Nav entry + ChatStatsPanel title share the default label.
		expect(screen.getAllByText('Chat Statistics').length).toBeGreaterThanOrEqual(2);
	});

	it('marks the active nav button with aria-current', () => {
		render(App);
		expect(screen.getByRole('button', { name: 'Chat Statistics' })).toHaveAttribute(
			'aria-current',
			'page'
		);
	});

	it('switches to the Home view from the nav', async () => {
		render(App);
		await fireEvent.click(screen.getByRole('button', { name: 'Home' }));
		expect(await screen.findByText('Hello, World!')).toBeInTheDocument();
		expect(screen.getByRole('button', { name: 'Home' })).toHaveAttribute('aria-current', 'page');
		// Previous view unmounts on switch (fresh-on-visit).
		expect(screen.queryByTestId('cs-total')).not.toBeInTheDocument();
	});

	it('shows backend status in the sidebar', () => {
		render(App);
		// Outside Tauri the store reports detached (no IPC, no rejection).
		expect(screen.getByText('Detached (no Tauri)')).toBeInTheDocument();
	});
});
