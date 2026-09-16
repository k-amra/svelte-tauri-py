/**
 * Theme store. Three-way: 'light' | 'dark' | 'system'.
 * On mount, resolves `system` against `prefers-color-scheme` and keeps it
 * live (if the user changes their OS theme, the class follows along).
 */
type Theme = 'light' | 'dark' | 'system';

const STORAGE_KEY = 'theme';

let current = $state<Theme>('system');
let mediaQuery: MediaQueryList | null = null;
let mediaListener: (() => void) | null = null;

function apply(): void {
	if (typeof document === 'undefined') return;
	const resolved = current === 'system' ? (mediaQuery?.matches ? 'dark' : 'light') : current;
	document.documentElement.classList.toggle('dark', resolved === 'dark');
}

function attachMediaListener(): void {
	// jsdom (tests) has no matchMedia; degrade to light-only there.
	if (typeof window === 'undefined' || typeof window.matchMedia !== 'function' || mediaQuery) {
		return;
	}
	mediaQuery = window.matchMedia('(prefers-color-scheme: dark)');
	mediaListener = () => {
		if (current === 'system') apply();
	};
	mediaQuery.addEventListener('change', mediaListener);
}

function setTheme(next: Theme): void {
	current = next;
	if (typeof window !== 'undefined') window.localStorage.setItem(STORAGE_KEY, next);
	attachMediaListener();
	apply();
}

export const theme = {
	get value(): Theme {
		return current;
	},
	/** The theme actually applied to the DOM (never 'system'). */
	get resolved(): 'light' | 'dark' {
		if (current !== 'system') return current;
		return mediaQuery?.matches ? 'dark' : 'light';
	},
	init(): void {
		if (typeof window === 'undefined') return;
		const stored = window.localStorage.getItem(STORAGE_KEY);
		current = stored === 'light' || stored === 'dark' || stored === 'system' ? stored : 'system';
		attachMediaListener();
		apply();
	},
	set: setTheme,
	/** Cycle light → dark → system → light. */
	cycle(): void {
		setTheme(current === 'light' ? 'dark' : current === 'dark' ? 'system' : 'light');
	}
};
