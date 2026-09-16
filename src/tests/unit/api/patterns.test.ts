import { describe, it, expect } from 'vitest';
import { URL_RE } from '$lib/api/patterns';

function fullMatch(text: string): string | null {
	const m = text.match(URL_RE);
	return m ? m[0] : null;
}

describe('URL_RE', () => {
	it('captures query strings in full', () => {
		expect(fullMatch('watch https://www.youtube.com/watch?v=abc123')).toBe(
			'https://www.youtube.com/watch?v=abc123'
		);
	});

	it('stops at whitespace, brackets and quotes', () => {
		expect(fullMatch('see (https://example.com/x) ok')).toBe('https://example.com/x');
		expect(fullMatch('a "https://example.com/y" b')).toBe('https://example.com/y');
	});

	it('finds nothing without a URL', () => {
		expect(fullMatch('just chatting, no links here')).toBeNull();
	});
});
