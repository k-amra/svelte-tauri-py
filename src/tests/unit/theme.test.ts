import { beforeEach, describe, expect, it, vi } from 'vitest';

// jsdom has no matchMedia; install a controllable mock before importing the
// store (module-level state persists for the whole file).
const mediaListeners = new Set<() => void>();
let systemPrefersDark = false;

function installMatchMedia() {
	vi.stubGlobal(
		'matchMedia',
		vi.fn().mockImplementation((query: string) => ({
			// Live getter: osThemeChanged() flips the value the store re-reads.
			get matches() {
				return query.includes('dark') ? systemPrefersDark : false;
			},
			addEventListener: (_: string, cb: () => void) => mediaListeners.add(cb),
			removeEventListener: (_: string, cb: () => void) => mediaListeners.delete(cb)
		}))
	);
}

function osThemeChanged(prefersDark: boolean) {
	systemPrefersDark = prefersDark;
	for (const cb of mediaListeners) cb();
}

describe('theme store', () => {
	beforeEach(() => {
		vi.unstubAllGlobals();
		localStorage.clear();
		document.documentElement.classList.remove('dark');
		systemPrefersDark = false;
		mediaListeners.clear();
		// Fresh module instance per test so `current` resets.
		vi.resetModules();
	});

	async function loadStore() {
		installMatchMedia();
		return import('$lib/theme.svelte');
	}

	it('defaults to system (light OS) without a stored value', async () => {
		const { theme } = await loadStore();
		theme.init();
		expect(theme.value).toBe('system');
		expect(theme.resolved).toBe('light');
		expect(document.documentElement.classList.contains('dark')).toBe(false);
	});

	it('follows a dark OS preference in system mode', async () => {
		const { theme } = await loadStore();
		theme.init();
		osThemeChanged(true);
		expect(theme.resolved).toBe('dark');
		expect(document.documentElement.classList.contains('dark')).toBe(true);
	});

	it('cycles light → dark → system and persists', async () => {
		const { theme } = await loadStore();
		theme.init();

		theme.set('light');
		expect(theme.resolved).toBe('light');
		expect(localStorage.getItem('theme')).toBe('light');

		theme.cycle();
		expect(theme.value).toBe('dark');
		expect(document.documentElement.classList.contains('dark')).toBe(true);
		expect(localStorage.getItem('theme')).toBe('dark');

		theme.cycle();
		expect(theme.value).toBe('system');
		// OS is light → resolved light.
		expect(theme.resolved).toBe('light');

		theme.cycle();
		expect(theme.value).toBe('light');
	});

	it('restores a dark preference from localStorage on init', async () => {
		localStorage.setItem('theme', 'dark');
		const { theme } = await loadStore();
		theme.init();
		expect(theme.value).toBe('dark');
		expect(theme.resolved).toBe('dark');
		expect(document.documentElement.classList.contains('dark')).toBe(true);
	});

	it('ignores invalid stored values', async () => {
		localStorage.setItem('theme', 'neon');
		const { theme } = await loadStore();
		theme.init();
		expect(theme.value).toBe('system');
	});
});
