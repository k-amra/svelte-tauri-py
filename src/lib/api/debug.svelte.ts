export type ApiDebugDirection = 'out' | 'in' | 'error';

export interface ApiDebugEntry {
	id: number;
	timestamp: string;
	direction: ApiDebugDirection;
	method: string;
	url: string;
	status?: number;
	payload?: string;
}

const MAX_ENTRIES = 200;
let nextId = 1;
let entries = $state<ApiDebugEntry[]>([]);

function preview(value: unknown): string | undefined {
	if (value === undefined || value === null || value === '') return undefined;

	const text = typeof value === 'string' ? value : JSON.stringify(value);
	return text.length > 4000 ? `${text.slice(0, 4000)}…` : text;
}

export const apiDebug = {
	get entries() {
		return entries;
	},

	add(entry: Omit<ApiDebugEntry, 'id' | 'timestamp'>) {
		entries = [
			...entries,
			{
				...entry,
				id: nextId++,
				timestamp: new Date().toISOString(),
				payload: preview(entry.payload)
			}
		].slice(-MAX_ENTRIES);
	},

	clear() {
		entries = [];
	}
};
