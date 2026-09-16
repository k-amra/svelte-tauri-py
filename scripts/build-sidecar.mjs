#!/usr/bin/env node
// Builds the Python sidecar with PyInstaller (onefile) and stages it for Tauri.
//
// Output layout (onefile: single exe, no _internal dir):
//   src-python/dist/api-server(.exe) -> src-tauri/binaries/api-server-<triple>(.exe)
//
// Usage:
//   bun scripts/build-sidecar.mjs [--target <triple>]
// Triple defaults to `rustc --print host-tuple` (e.g. x86_64-pc-windows-msvc).
// Wrong triple suffix = #1 setup failure: Tauri can't find the sidecar.

import { execSync } from 'node:child_process';
import { cpSync, existsSync, mkdirSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = dirname(fileURLToPath(import.meta.url));
const root = join(__dirname, '..');

function argValue(name) {
	const i = process.argv.indexOf(name);
	return i >= 0 && i + 1 < process.argv.length ? process.argv[i + 1] : undefined;
}

function getTriple() {
	const override = argValue('--target');
	if (override) return override;
	try {
		return execSync('rustc --print host-tuple', { encoding: 'utf8' }).trim();
	} catch {
		// Rust 1.83 and older lack --print host-tuple; parse `rustc -Vv`.
		const out = execSync('rustc -Vv', { encoding: 'utf8' });
		const m = out.match(/host:\s*(\S+)/);
		if (!m) throw new Error('cannot determine rust target triple');
		return m[1];
	}
}

const triple = getTriple();
const ext = process.platform === 'win32' ? '.exe' : '';
console.log(`[build:sidecar] target triple: ${triple}`);

const binDir = join(root, 'src-tauri', 'binaries');
const destExe = join(binDir, `api-server-${triple}${ext}`);

// The release pipeline builds + signs the sidecar BEFORE `tauri build`, whose
// `beforeBuildCommand` would otherwise rebuild here and clobber the signature
// (plus pay for a second PyInstaller run). SIDECAR_PREBUILT=1 reuses it.
if (process.env.SIDECAR_PREBUILT === '1' && existsSync(destExe)) {
	console.log(
		`[build:sidecar] SIDECAR_PREBUILT=1 and ${destExe} exists — skipping rebuild (preserves signature).`
	);
	process.exit(0);
}

execSync('uv run pyinstaller api_server.spec --noconfirm', {
	cwd: join(root, 'src-python'),
	stdio: 'inherit'
});

const builtExe = join(root, 'src-python', 'dist', `api-server${ext}`);
if (!existsSync(builtExe)) {
	throw new Error(`PyInstaller output missing: ${builtExe}`);
}

mkdirSync(binDir, { recursive: true });
cpSync(builtExe, destExe);
console.log(`[build:sidecar] exe -> ${destExe}`);

console.log('[build:sidecar] done. Verify: binary name ends with the Rust target triple,');
console.log('  capability `name` matches `externalBin`, and python prints READY with flush=True.');
