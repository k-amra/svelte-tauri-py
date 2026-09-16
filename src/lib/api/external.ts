/**
 * Open a URL in the user's default browser.
 *
 * In Tauri, `<a target="_blank">` and `window.open()` do not reliably reach
 * the OS browser — the WebView either blocks them or opens an in-app window.
 * The shell plugin's `open()` is the supported route (requires the
 * `shell:allow-open` capability). In plain `vite dev` there is no Tauri, so
 * we fall back to `window.open` so the UI stays testable.
 */
import { open } from '@tauri-apps/plugin-shell';

export async function openExternal(url: string): Promise<void> {
	// Only hand http(s) to the OS; anything else could be a footgun
	// (file://, javascript:, custom schemes that shell could execute).
	if (!/^https?:\/\//i.test(url)) {
		console.warn('[external] refusing to open non-http(s) URL:', url);
		return;
	}

	const inTauri = typeof window !== 'undefined' && '__TAURI_INTERNALS__' in window;
	if (inTauri) {
		try {
			await open(url);
			return;
		} catch (e) {
			console.warn('[external] shell.open failed, falling back:', e);
		}
	}
	// Browser-only dev fallback. `noopener,noreferrer` prevents the opened
	// page from reaching back into `window.opener`.
	window.open(url, '_blank', 'noopener,noreferrer');
}
