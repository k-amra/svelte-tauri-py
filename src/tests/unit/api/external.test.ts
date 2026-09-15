import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';

vi.mock('@tauri-apps/plugin-shell', () => ({
	open: vi.fn()
}));

import { open } from '@tauri-apps/plugin-shell';
import { openExternal } from '$lib/api/external';

const mockShellOpen = vi.mocked(open);
const TAURI_KEY = '__TAURI_INTERNALS__' as const;

describe('openExternal', () => {
	let windowOpen: ReturnType<typeof vi.fn>;

	beforeEach(() => {
		mockShellOpen.mockReset();
		windowOpen = vi.fn().mockReturnValue(null);
		vi.stubGlobal('open', undefined);
		window.open = windowOpen as unknown as typeof window.open;
		delete (window as unknown as Record<string, unknown>)[TAURI_KEY];
		vi.spyOn(console, 'warn').mockImplementation(() => {});
	});

	afterEach(() => {
		vi.unstubAllGlobals();
		vi.restoreAllMocks();
		delete (window as unknown as Record<string, unknown>)[TAURI_KEY];
	});

	it('refuses non-http(s) URLs without touching shell or window', async () => {
		await openExternal('javascript:alert(1)');
		await openExternal('file:///etc/passwd');
		expect(mockShellOpen).not.toHaveBeenCalled();
		expect(windowOpen).not.toHaveBeenCalled();
	});

	it('falls back to window.open outside Tauri', async () => {
		await openExternal('https://example.com/x');
		expect(mockShellOpen).not.toHaveBeenCalled();
		expect(windowOpen).toHaveBeenCalledWith(
			'https://example.com/x',
			'_blank',
			'noopener,noreferrer'
		);
	});

	it('uses shell.open inside Tauri', async () => {
		(window as unknown as Record<string, unknown>)[TAURI_KEY] = {};
		mockShellOpen.mockResolvedValue(undefined);

		await openExternal('https://example.com/x');
		expect(mockShellOpen).toHaveBeenCalledWith('https://example.com/x');
		expect(windowOpen).not.toHaveBeenCalled();
	});

	it('falls back to window.open when shell.open throws', async () => {
		(window as unknown as Record<string, unknown>)[TAURI_KEY] = {};
		mockShellOpen.mockRejectedValue(new Error('denied'));

		await openExternal('https://example.com/x');
		expect(windowOpen).toHaveBeenCalledWith(
			'https://example.com/x',
			'_blank',
			'noopener,noreferrer'
		);
	});
});
