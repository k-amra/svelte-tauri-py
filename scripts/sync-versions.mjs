#!/usr/bin/env node
// Sync version from package.json -> tauri.conf.json, Cargo.toml, pyproject.toml.
// Usage: bun run version or: bun scripts/sync-versions.mjs [version]
import { readFileSync, writeFileSync } from 'node:fs';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const pkg = JSON.parse(readFileSync(join(root, 'package.json'), 'utf8'));
const version = process.argv[2] ?? pkg.version;
console.log(`[version] syncing ${version}`);

// tauri.conf.json
const tauriPath = join(root, 'src-tauri', 'tauri.conf.json');
const tauri = JSON.parse(readFileSync(tauriPath, 'utf8'));
tauri.version = version;
writeFileSync(tauriPath, JSON.stringify(tauri, null, 2) + '\n');

function replacePackageVersion(toml, version, file) {
	const lines = toml.split(/\r?\n/);
	let inPackage = false;
	let replaced = false;

	for (let i = 0; i < lines.length; i += 1) {
		const line = lines[i];
		if (/^\s*\[package\]\s*$/.test(line)) {
			inPackage = true;
			continue;
		}
		if (/^\s*\[[^\]]+\]\s*$/.test(line)) inPackage = false;
		if (inPackage && /^\s*version\s*=\s*"/.test(line)) {
			lines[i] = line.replace(/(version\s*=\s*")[^"]*(".*)$/, `$1${version}$2`);
			replaced = true;
			break;
		}
	}

	if (!replaced) throw new Error(`[version] package version not found in ${file}`);
	return lines.join('\n');
}

// Cargo.toml ([package] version only; preserves comments and formatting)
const cargoPath = join(root, 'src-tauri', 'Cargo.toml');
let cargo = readFileSync(cargoPath, 'utf8');
cargo = replacePackageVersion(cargo, version, cargoPath);
writeFileSync(cargoPath, cargo);

// src-python/pyproject.toml
const pyPath = join(root, 'src-python', 'pyproject.toml');
try {
	let py = readFileSync(pyPath, 'utf8');
	py = py.replace(/(^version = ")[^"]+(")/m, `$1${version}$2`);
	writeFileSync(pyPath, py);
} catch {
	console.warn('[version] src-python/pyproject.toml not found, skipping');
}
console.log(
	'[version] done. Also update bun.lock via `bun install` and Cargo.lock via `cargo check`.'
);
