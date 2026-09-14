import { render, screen } from '@testing-library/svelte';
import { describe, expect, it } from 'vitest';
import ChannelSummaryCards from '$lib/components/ChannelSummaryCards.svelte';
import type { ChannelSummary } from '$lib/api/chatStats';

const summaries: ChannelSummary[] = [
	{
		channel: 'main',
		total_messages: 5000,
		unique_chatters: 120,
		top_chatters: [
			{
				user_id: '1',
				username: 'alice',
				messageCount: 900,
				activeDays: 5,
				firstSeen: null,
				lastSeen: null,
				engagement_score: null
			},
			{
				user_id: '2',
				username: 'bob',
				messageCount: 300,
				activeDays: 4,
				firstSeen: null,
				lastSeen: null,
				engagement_score: null
			}
		],
		top_emotes: [{ name: 'Kappa', count: 42 }],
		top_words: [],
		top_commands: [],
		top_domains: [],
		top_mentions: [],
		roles: [],
		peak_concurrent_chatters: 90,
		messages_per_day: [],
		first_message: null,
		last_message: null
	},
	{
		channel: 'alt',
		total_messages: 1000,
		unique_chatters: 40,
		top_chatters: [],
		top_emotes: [],
		top_words: [],
		top_commands: [],
		top_domains: [],
		top_mentions: [],
		roles: [],
		peak_concurrent_chatters: 20,
		messages_per_day: [],
		first_message: null,
		last_message: null
	}
];

describe('ChannelSummaryCards', () => {
	it('renders one card per channel with headline numbers', () => {
		render(ChannelSummaryCards, { summaries });
		expect(screen.getByText('main')).toBeInTheDocument();
		expect(screen.getByText('alt')).toBeInTheDocument();
		expect(screen.getByText(/^5,?000$/)).toBeInTheDocument();
		expect(screen.getByText(/^1,?000$/)).toBeInTheDocument();
		expect(screen.getByText('2 channels · pooled totals above, splits below')).toBeInTheDocument();
		// Pooled total in the header (5000 + 1000).
		expect(screen.getByText(/^6,?000 total messages$/)).toBeInTheDocument();
	});

	it('shows share-of-total and msgs-per-chatter per channel', () => {
		render(ChannelSummaryCards, { summaries });
		// main: 5000/6000 = 83.3%, alt: 1000/6000 = 16.7%.
		expect(screen.getByText('83.3% of total')).toBeInTheDocument();
		expect(screen.getByText('16.7% of total')).toBeInTheDocument();
		// main: 5000/120 = 41.7 msgs/chatter; alt: 1000/40 = 25.0.
		expect(screen.getByText('41.7')).toBeInTheDocument();
		expect(screen.getByText('25.0')).toBeInTheDocument();
		// A channel with zero chatters shows an em-dash instead of NaN.
		const zeroed: ChannelSummary[] = summaries.map((s) => ({
			...s,
			total_messages: 0,
			unique_chatters: 0
		}));
		render(ChannelSummaryCards, { summaries: zeroed });
		expect(screen.getAllByText('—').length).toBeGreaterThan(0);
	});

	it('caps the listed chatters/emotes and hides empty lists', () => {
		render(ChannelSummaryCards, { summaries });
		expect(screen.getByText('alice')).toBeInTheDocument();
		// alt has no top chatters → no list for that card.
		expect(screen.getAllByText('Top chatters')).toHaveLength(1);
		expect(screen.getByText('Kappa')).toBeInTheDocument();
	});

	it('renders zero-height bars (not NaN widths) when every channel is empty', () => {
		const zeroed: ChannelSummary[] = summaries.map((s) => ({ ...s, total_messages: 0 }));
		const { container } = render(ChannelSummaryCards, { summaries: zeroed });
		const bars = container.querySelectorAll<HTMLDivElement>('[style*="width"]');
		expect(bars.length).toBeGreaterThan(0);
		for (const bar of bars) {
			expect(bar.style.width).not.toMatch(/NaN/);
		}
	});
});
