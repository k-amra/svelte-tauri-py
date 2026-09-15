import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/svelte';
import AllLinksDialog from '$lib/components/results/AllLinksDialog.svelte';

vi.mock('$lib/api/external', () => ({
	openExternal: vi.fn()
}));

import { openExternal } from '$lib/api/external';

const mockOpenExternal = vi.mocked(openExternal);

function stubDialogMethods() {
	// jsdom has no top layer (`showModal`/`close` are missing): stub both so
	// the open-state $effect passes, mirroring the browser by reflecting
	// the `open` attribute.
	const proto = HTMLDialogElement.prototype as unknown as Record<string, unknown>;
	if (typeof proto.showModal !== 'function') {
		proto.showModal = function (this: HTMLDialogElement) {
			this.setAttribute('open', '');
		};
	}
	if (typeof proto.close !== 'function') {
		proto.close = function (this: HTMLDialogElement) {
			this.removeAttribute('open');
		};
	}
	vi.spyOn(HTMLDialogElement.prototype, 'showModal').mockImplementation(function (
		this: HTMLDialogElement
	) {
		this.setAttribute('open', '');
	});
	vi.spyOn(HTMLDialogElement.prototype, 'close').mockImplementation(function (
		this: HTMLDialogElement
	) {
		this.removeAttribute('open');
	});
}

describe('AllLinksDialog', () => {
	beforeEach(() => {
		stubDialogMethods();
		mockOpenExternal.mockReset();
	});

	afterEach(() => {
		vi.restoreAllMocks();
		document.body.innerHTML = '';
	});

	it('flags a hit cap in the header', () => {
		render(AllLinksDialog, {
			open: true,
			urls: [
				{ url: 'https://example.com/a', count: 5 },
				{ url: 'https://example.com/b', count: 3 }
			],
			maxCount: 5,
			uniqueUrlCount: 5000
		});
		expect(screen.getByText(/Showing 2 of 5000 unique/)).toBeInTheDocument();
	});

	it('shows the plain count when nothing is capped', () => {
		render(AllLinksDialog, {
			open: true,
			urls: [{ url: 'https://example.com/a', count: 5 }],
			maxCount: 5,
			uniqueUrlCount: 1
		});
		expect(screen.getByText('1 unique · ranked by paste count')).toBeInTheDocument();
	});

	it('carries the hook the centering stylesheet targets', () => {
		// jsdom applies neither component CSS (vite doesn't inject it here)
		// nor real top-layer layout, so the `position: fixed; inset: 0;
		// margin: auto` declarations can't be evaluated in this environment.
		// Verified instead via `vite build`: the shipped bundle contains
		// `.all-links-dialog.<hash>{...position:fixed;...margin:auto...}` plus
		// the `::backdrop` rule. Here we pin the hook the stylesheet keys on.
		render(AllLinksDialog, { open: true, urls: [], maxCount: 1, uniqueUrlCount: 0 });
		const dialog = document.querySelector('dialog');
		expect(dialog?.classList.contains('all-links-dialog')).toBe(true);
	});

	it('routes URL clicks through the external opener', async () => {
		render(AllLinksDialog, {
			open: true,
			urls: [{ url: 'https://example.com/a', count: 5 }],
			maxCount: 5,
			uniqueUrlCount: 1
		});
		await fireEvent.click(screen.getByRole('button', { name: 'https://example.com/a' }));
		expect(mockOpenExternal).toHaveBeenCalledWith('https://example.com/a');
	});
});
