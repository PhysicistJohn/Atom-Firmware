#!/usr/bin/env node

import { access } from 'node:fs/promises';
import { dirname, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const source = fileURLToPath(import.meta.url);
const firmwareRoot = resolve(dirname(source), '..');
const twinRoot = resolve(
  process.env.TINYSA_TWIN_ROOT ?? resolve(firmwareRoot, '../TinySA_Twin'),
);
const target = resolve(twinRoot, 'tools/atomizer-twin-bridge.mjs');

if (target === source) {
  throw new Error('TINYSA_TWIN_ROOT resolves the compatibility bridge to itself');
}
process.env.TINYSA_ARTIFACTS_DIR ??= resolve(firmwareRoot, '.artifacts');
await access(target);
await import(pathToFileURL(target).href);
