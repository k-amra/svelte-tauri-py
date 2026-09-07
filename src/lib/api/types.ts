/**
 * Generated from FastAPI's /openapi.json via `bun run gen:types`.
 * Do not hand-edit — regenerate instead. This checked-in copy is a minimal
 * placeholder so `svelte-check` passes without a running backend.
 */
export interface paths {
	'/health': {
		get: {
			responses: {
				200: { content: { 'application/json': { status: string } } };
			};
		};
	};
}

export type ScriptMeta = {
	name: string;
	description: string;
	params_schema: Record<string, unknown>;
	result_schema: Record<string, unknown>;
};

export type RunScriptResponse = {
	name: string;
	result: unknown;
	events: Array<{ progress: number; message: string }>;
};

export type JobStatus = {
	job_id: string;
	script: string;
	status: 'running' | 'done' | 'error';
	progress: number;
	message: string;
	result: unknown;
	error: string | null;
};
