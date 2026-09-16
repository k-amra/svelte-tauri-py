/**
 * Client-side export helpers for the chat-stats panel.
 *
 * All exports happen in the WebView — no backend round-trip, no new deps.
 */
import type { ChatStatsResult } from './chatStats';

function csvEscape(value: unknown): string {
	if (value === null || value === undefined) return '';
	const s = String(value);
	return /[",\n\r]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
}

function toCsv(rows: (string | number | null | undefined)[][]): string {
	// Excel/LibreOffice prefer CRLF; \r\n also works fine in every other tool.
	return rows.map((r) => r.map(csvEscape).join(',')).join('\r\n');
}

function download(filename: string, content: string, mime: string): void {
	const blob = new Blob([content], { type: mime });
	const url = URL.createObjectURL(blob);
	const a = document.createElement('a');
	a.href = url;
	a.download = filename;
	document.body.appendChild(a);
	a.click();
	a.remove();
	URL.revokeObjectURL(url);
}

/** `demonzz1_2026-09-04_2026-09-11` — safe on all filesystems. */
function baseName(channel: string, fromISO: string, toISO: string): string {
	const safeChannel = channel.replace(/[^A-Za-z0-9_-]/g, '_');
	const from = fromISO.slice(0, 10);
	const to = toISO.slice(0, 10);
	return `${safeChannel}_${from}_${to}`;
}

export function exportStatsJson(
	stats: ChatStatsResult,
	channel: string,
	fromISO: string,
	toISO: string
): void {
	download(
		`${baseName(channel, fromISO, toISO)}_stats.json`,
		JSON.stringify(stats, null, 2),
		'application/json'
	);
}

export function exportTopChattersCsv(
	stats: ChatStatsResult,
	channel: string,
	fromISO: string,
	toISO: string
): void {
	const rows: (string | number | null)[][] = [
		[
			'user_id',
			'username',
			'messageCount',
			'activeDays',
			'firstSeen',
			'lastSeen',
			'engagement_score'
		]
	];
	for (const c of stats.top_chatters) {
		rows.push([
			c.user_id,
			c.username,
			c.messageCount,
			c.activeDays,
			c.firstSeen,
			c.lastSeen,
			c.engagement_score
		]);
	}
	download(
		`${baseName(channel, fromISO, toISO)}_top_chatters.csv`,
		toCsv(rows),
		'text/csv;charset=utf-8'
	);
}

/** One CSV per section, concatenated into a single file with blank-line separators. */
export function exportAllSectionsCsv(
	stats: ChatStatsResult,
	channel: string,
	fromISO: string,
	toISO: string
): void {
	const sections: string[] = [];

	const push = (title: string, header: string[], rows: (string | number | null)[][]) => {
		sections.push(`# ${title}`);
		sections.push(toCsv([header, ...rows]));
		sections.push('');
	};

	push(
		'Top chatters',
		['user_id', 'username', 'messageCount', 'activeDays', 'firstSeen', 'lastSeen'],
		stats.top_chatters.map((c) => [
			c.user_id,
			c.username,
			c.messageCount,
			c.activeDays,
			c.firstSeen,
			c.lastSeen
		])
	);
	push(
		'Top words',
		['word', 'count'],
		stats.top_words.map((w) => [w.word, w.count])
	);
	push(
		'Top emotes',
		['name', 'count'],
		stats.top_emotes.map((e) => [e.name, e.count])
	);
	push(
		'Emote pairs',
		['emote1', 'emote2', 'count'],
		stats.top_emote_pairs.map((p) => [p.emote1, p.emote2, p.count])
	);
	push(
		'Commands',
		['name', 'count', 'unique_users'],
		stats.top_commands.map((c) => [c.name, c.count, c.unique_users])
	);
	push(
		'Domains',
		['domain', 'count'],
		stats.top_domains.map((d) => [d.domain, d.count])
	);
	push(
		'Links (by paste count)',
		['url', 'count'],
		stats.top_urls.map((u) => [u.url, u.count])
	);
	push(
		'Mentions',
		['username', 'count'],
		stats.top_mentions.map((m) => [m.username, m.count])
	);
	push(
		'Messages per day',
		['date', 'count'],
		stats.messages_per_day.map((d) => [d.date, d.count])
	);
	push(
		'Roles',
		['role', 'messages', 'unique_users'],
		stats.roles.map((r) => [r.role, r.messages, r.unique_users])
	);
	if (stats.staff_list.length > 0) {
		push(
			'Staff',
			['user_id', 'username', 'role', 'messageCount', 'firstSeen', 'lastSeen'],
			stats.staff_list.map((s) => [
				s.user_id,
				s.username,
				s.role,
				s.messageCount,
				s.firstSeen,
				s.lastSeen
			])
		);
	}
	if (stats.subscriber_list.length > 0) {
		push(
			'Subscribers',
			['user_id', 'username', 'messageCount', 'firstSeen', 'lastSeen'],
			stats.subscriber_list.map((s) => [
				s.user_id,
				s.username,
				s.messageCount,
				s.firstSeen,
				s.lastSeen
			])
		);
	}
	if (stats.anomalies_5m.length > 0) {
		push(
			'Anomalies (5m)',
			['window_start', 'message_count', 'z_score', 'p_value'],
			stats.anomalies_5m.map((a) => [a.window_start, a.message_count, a.z_score, a.p_value])
		);
	}

	download(
		`${baseName(channel, fromISO, toISO)}_all_sections.csv`,
		sections.join('\r\n'),
		'text/csv;charset=utf-8'
	);
}

/** Discord/blog-friendly plain-text summary of the headline numbers. */
export function buildSummaryMarkdown(
	stats: ChatStatsResult,
	channel: string,
	fromISO: string,
	toISO: string
): string {
	const topChatter = stats.top_chatters[0];
	const topEmote = stats.top_emotes[0];
	const lines = [
		`**${channel}** — ${fromISO.slice(0, 10)} → ${toISO.slice(0, 10)}`,
		`${stats.total_messages.toLocaleString()} messages · ${stats.unique_chatters.toLocaleString()} chatters · ${stats.days_spanned} days`,
		topChatter
			? `Top chatter: ${topChatter.username} (${topChatter.messageCount.toLocaleString()})`
			: null,
		topEmote ? `Top emote: ${topEmote.name} (${topEmote.count.toLocaleString()})` : null,
		stats.peak_concurrent_chatters != null
			? `Peak concurrent: ${stats.peak_concurrent_chatters} (5m window)`
			: null
	].filter((x): x is string => x !== null);
	return lines.join('\n');
}

export async function copySummaryToClipboard(
	stats: ChatStatsResult,
	channel: string,
	fromISO: string,
	toISO: string
): Promise<void> {
	await navigator.clipboard.writeText(buildSummaryMarkdown(stats, channel, fromISO, toISO));
}
