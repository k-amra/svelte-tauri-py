#!/usr/bin/env node
// Consolidate all source files (no tests, deps, builds, caches, locks,
// binaries, or docs) into one txt file, for feeding to an LLM or for review.
// A companion file containing *only* test files is written alongside it.
//
// Usage:
//   bun scripts/consolidate-source.mjs
//     -> consolidated.txt (source) + consolidated-tests.txt (tests)
//   bun scripts/consolidate-source.mjs --out snapshot.txt
//     -> snapshot.txt + snapshot-tests.txt
//   bun scripts/consolidate-source.mjs --out src.txt --tests-out t.txt
//   bun scripts/consolidate-source.mjs --root /path/to/repo
//
// Exit code 0 on success. Fails loudly if neither source nor test files
// matched (usually a symptom of a bad --root, not a real "empty repo").

import { readFileSync, readdirSync, writeFileSync } from 'node:fs';
import { dirname, join, relative, resolve, sep } from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = dirname(fileURLToPath(import.meta.url));
const repoRoot = resolve(__dirname, '..');

function argValue(name) {
	const i = process.argv.indexOf(name);
	return i >= 0 && i + 1 < process.argv.length ? process.argv[i + 1] : undefined;
}

const root = resolve(argValue('--root') ?? repoRoot);

// `consolidated.txt` -> `consolidated-tests.txt`; keeps extension if present.
function deriveTestsPath(sourcePath) {
	const dir = dirname(sourcePath);
	const base = sourcePath.slice(dir.length + 1);
	const dot = base.lastIndexOf('.');
	return dot < 0
		? join(dir, `${base}-tests`)
		: join(dir, `${base.slice(0, dot)}-tests${base.slice(dot)}`);
}

const sourceOutPath = resolve(argValue('--out') ?? join(root, 'consolidated.txt'));
const testsOutPath = resolve(argValue('--tests-out') ?? deriveTestsPath(sourceOutPath));

// --- Exclusions -------------------------------------------------------------
// Directory names: any directory whose *basename* matches is skipped (with
// all descendants), regardless of depth.
const SKIP_DIRS = new Set([
	'.git',
	'node_modules',
	'.svelte-kit',
	'.vite',
	'dist',
	'dist-ssr',
	'build',
	'target',
	'gen',
	'binaries',
	'__pycache__',
	'.venv',
	'venv',
	'.mypy_cache',
	'.pytest_cache',
	'.ruff_cache',
	'.turbo',
	'.cache',
	'coverage',
	'.idea',
	'.vscode-test'
]);

// `.github` is deliberately NOT in SKIP_DIRS: workflows and renovate.json
// belong in the snapshot. KEEP_DIRS exists for future dirs that need the
// same carve-out.
const KEEP_DIRS = new Set(['.github']);

// File names: exact basename matches are skipped anywhere in the tree.
const SKIP_FILE_NAMES = new Set([
	// locks
	'bun.lock',
	'bun.lockb',
	'package-lock.json',
	'yarn.lock',
	'pnpm-lock.yaml',
	'Cargo.lock',
	'poetry.lock',
	'uv.lock',
	// env / secrets
	'.env',
	'.env.local',
	'.env.development',
	'.env.production',
	// OS noise
	'.DS_Store',
	'Thumbs.db'
]);

// File extensions: skipped anywhere (case-insensitive).
const SKIP_EXTS = new Set([
	// docs / prose
	'.md',
	'.mdx',
	'.rst',
	'.txt',
	// binaries / images / fonts
	'.png',
	'.jpg',
	'.jpeg',
	'.gif',
	'.webp',
	'.svg',
	'.ico',
	'.icns',
	'.ttf',
	'.otf',
	'.woff',
	'.woff2',
	'.pdf',
	'.zip',
	'.tar',
	'.gz',
	'.7z',
	// compiled
	'.pyc',
	'.pyo',
	'.class',
	'.o',
	'.obj',
	'.so',
	'.dylib',
	'.dll',
	'.exe',
	'.wasm',
	// misc
	'.log',
	'.map',
	'.tsbuildinfo'
]);

// Path fragments (relative to root, forward slashes): skip the whole subtree.
const SKIP_PATH_PREFIXES = [
	'src-tauri/target',
	'src-tauri/gen',
	'src-python/.venv',
	'src-python/dist',
	'src-python/build'
];

// Test files: routed to the *tests* snapshot, not the source snapshot.
const TEST_PATH_PATTERNS = [
	/(^|\/)tests?(\/|$)/i, // tests/ dirs (Python tests, Vitest lives in src/tests)
	/(^|\/)__tests__(\/|$)/i,
	/\.(test|spec)\.[cm]?[jt]sx?$/i, // *.test.ts, *.spec.js, *.test.svelte.ts
	/_test\.(py|rs)$/i
];

// Noise: skipped from BOTH snapshots (generated stubs, tool config that's
// low value, test-run output dirs — these are not tests themselves).
const NOISE_PATH_PATTERNS = [
	/(^|\/)test-results(\/|$)/i,
	/\.d\.ts$/i,
	/(^|\/)\.prettierignore$|(^|\/)\.gitignore$|(^|\/)\.taurignore$/i,
	/\.pyi$/i
];

// Which extensions to include. Anything not listed is skipped, so adding a
// new language is one line here. (Extensions are lowercased before lookup.)
const INCLUDE_EXTS = new Set([
	'.ts',
	'.tsx',
	'.mts',
	'.cts',
	'.js',
	'.jsx',
	'.mjs',
	'.cjs',
	'.svelte',
	'.css',
	'.html',
	'.py',
	'.rs',
	'.toml',
	'.json',
	'.jsonc',
	'.json5',
	'.yaml',
	'.yml',
	'.sh',
	'.bash',
	'.ps1',
	'.sql',
	'.spec' // PyInstaller .spec files (Python syntax)
]);

// Files that pass the extension filter but should still be skipped by name.
const EXTRA_SKIP_RELATIVE = new Set([
	'consolidated.txt',
	'consolidated-tests.txt',
	'snapshot.txt',
	'snapshot-tests.txt',
	'.prettierrc'
]);

// --- Walk -------------------------------------------------------------------

const HEADER_LINE = '='.repeat(80);

function shouldSkipDir(absDir, relDir) {
	const name = absDir.split(sep).pop();
	if (name && KEEP_DIRS.has(name)) return false;
	if (name && SKIP_DIRS.has(name)) return true;
	const prefix = relDir ? relDir + '/' : '';
	for (const p of SKIP_PATH_PREFIXES) {
		if (prefix === p + '/' || prefix === p) return true;
	}
	return false;
}

function isTrivialInit(absFile) {
	const body = readFileSync(absFile, 'utf8');
	const stripped = body
		.replace(/^\s*"""[\s\S]*?"""\s*/, '')
		.replace(/^\s*from __future__ import .*\n/m, '')
		.trim();
	return stripped.length === 0;
}

/**
 * Classify a candidate file:
 *   'skip'   - excluded from both snapshots
 *   'source' - goes into the source snapshot
 *   'test'   - goes into the tests snapshot
 */
function classifyFile(absFile, relFile) {
	const name = absFile.split(sep).pop() ?? '';
	if (SKIP_FILE_NAMES.has(name)) return 'skip';
	if (EXTRA_SKIP_RELATIVE.has(relFile)) return 'skip';

	const dot = name.lastIndexOf('.');
	const ext = dot >= 0 ? name.slice(dot).toLowerCase() : '';
	if (SKIP_EXTS.has(ext)) return 'skip';
	if (!INCLUDE_EXTS.has(ext)) return 'skip';

	if (name === '__init__.py' && isTrivialInit(absFile)) return 'skip';

	for (const re of NOISE_PATH_PATTERNS) {
		if (re.test(relFile)) return 'skip';
	}
	for (const re of TEST_PATH_PATTERNS) {
		if (re.test(relFile)) return 'test';
	}
	return 'source';
}

function walk(absDir) {
	const entries = readdirSync(absDir, { withFileTypes: true });
	// Deterministic order: directories and files interleaved, sorted by name,
	// with directories first so the tree reads top-down in the output.
	entries.sort((a, b) => {
		if (a.isDirectory() && !b.isDirectory()) return -1;
		if (!a.isDirectory() && b.isDirectory()) return 1;
		return a.name.localeCompare(b.name);
	});

	const files = [];
	for (const entry of entries) {
		const abs = join(absDir, entry.name);
		const rel = relative(root, abs).split(sep).join('/');
		if (entry.isDirectory()) {
			if (shouldSkipDir(abs, rel)) continue;
			files.push(...walk(abs));
		} else if (entry.isFile()) {
			const category = classifyFile(abs, rel);
			if (category === 'skip') continue;
			files.push({ abs, rel, category });
		}
	}
	return files;
}

// --- Render -----------------------------------------------------------------

const allFiles = walk(root).sort((a, b) => a.rel.localeCompare(b.rel));
const sourceFiles = allFiles.filter((f) => f.category === 'source');
const testFiles = allFiles.filter((f) => f.category === 'test');

if (sourceFiles.length === 0 && testFiles.length === 0) {
	console.error(`No source or test files matched under ${root}.`);
	console.error('Check --root or the SKIP_* / INCLUDE_EXTS filters.');
	process.exit(1);
}

function renderSnapshot(files, { title, subtitle }) {
	const parts = [`# ${title}`, `# ${subtitle}`, ''];
	let totalBytes = 0;
	for (const { abs, rel } of files) {
		const body = readFileSync(abs, 'utf8');
		totalBytes += Buffer.byteLength(body, 'utf8');
		parts.push(HEADER_LINE);
		parts.push(`FILE: ${rel}`);
		parts.push(HEADER_LINE);
		parts.push(body.replace(/\s+$/, '')); // trim trailing whitespace per file
		parts.push('');
		parts.push('');
	}
	return { text: parts.join('\n'), totalBytes };
}

const source = renderSnapshot(sourceFiles, {
	title: 'Consolidated source snapshot (code only, no tests)',
	subtitle:
		'Generated from the working tree; tests, dependencies, build outputs, caches, locks, binaries and documentation are omitted.'
});

const tests = renderSnapshot(testFiles, {
	title: 'Consolidated tests snapshot (tests only)',
	subtitle:
		'Generated from the working tree; only test files are included. Dependencies, build outputs, caches, locks, binaries and documentation are omitted.'
});

writeFileSync(sourceOutPath, source.text, 'utf8');
writeFileSync(testsOutPath, tests.text, 'utf8');

const relSource = relative(root, sourceOutPath) || sourceOutPath;
const relTests = relative(root, testsOutPath) || testsOutPath;

console.log(`[consolidate] root:   ${root}`);
console.log(
	`[consolidate] source: ${sourceFiles.length} files, ${source.totalBytes.toLocaleString()} bytes -> ${relSource}`
);
console.log(
	`[consolidate] tests:  ${testFiles.length} files, ${tests.totalBytes.toLocaleString()} bytes -> ${relTests}`
);
