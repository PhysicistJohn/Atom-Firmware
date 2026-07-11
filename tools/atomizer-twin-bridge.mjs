#!/usr/bin/env node

import { spawn } from 'node:child_process';
import { createInterface } from 'node:readline';
import { mkdtemp, readFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const CONTRACT_VERSION = 1;
const ROOT = resolve(fileURLToPath(new URL('..', import.meta.url)));
const PROMPT = '(zs407) ';
const BOOT_TIMEOUT_MS = 120_000;
const COMMAND_TIMEOUT_MS = 120_000;
const MAX_REQUEST_BYTES = 64 * 1024;
const MAX_POINTS = 450;
const MIN_POINTS = 20;

class RenodeMonitor {
  #child;
  #buffer = '';
  #waiters = [];
  #closed;

  constructor() {
    this.#child = spawn(join(ROOT, 'tools/run-digital-twin.sh'), [], {
      cwd: ROOT,
      env: { ...process.env },
      stdio: ['pipe', 'pipe', 'pipe'],
    });
    this.#closed = new Promise((_, reject) => {
      this.#child.once('error', (error) => reject(new Error(`Renode failed to start: ${error.message}`)));
      this.#child.once('exit', (code, signal) => {
        const error = new Error(`Renode exited before bridge shutdown (code ${String(code)}, signal ${String(signal)})`);
        while (this.#waiters.length) this.#waiters.shift()?.reject(error);
        reject(error);
      });
    });
    this.#closed.catch(() => undefined);
    this.#child.stdout.setEncoding('utf8');
    this.#child.stdout.on('data', (chunk) => { this.#buffer += chunk; this.#drain(); });
    this.#child.stderr.setEncoding('utf8');
    this.#child.stderr.on('data', (chunk) => process.stderr.write(`[renode] ${chunk}`));
  }

  async start() {
    await this.#readPrompt(BOOT_TIMEOUT_MS);
    await this.command('emulation RunFor "1.5"', BOOT_TIMEOUT_MS);
    const boot = await this.command('twinStatus AssertBooted');
    requireLine(boot, 'ZS407_TWIN_BOOT=PASS');
    await this.command('spi1.spiFabric.receiver ClearFixedRssi');
    await this.command('spi1.spiFabric.receiver ClearTones');
    await this.command('spi1.spiFabric.receiver SetNoiseFloorDbm -110');
    await this.command('spi1.spiFabric.receiver AddTone 98000000 -52 300000');
    return requireLine(boot, 'ZS407_TWIN_BOOT=PASS');
  }

  async command(command, timeoutMs = COMMAND_TIMEOUT_MS) {
    if (!this.#child.stdin.writable) throw new Error('Renode monitor stdin is unavailable');
    this.#child.stdin.write(`${command}\n`);
    const raw = await this.#readPrompt(timeoutMs);
    const cleaned = cleanMonitorOutput(raw, command);
    if (/Error while executing command|RecoverableException|assertion failed|Exception:/i.test(cleaned)) {
      throw new Error(`Renode command failed: ${singleLine(cleaned)}`);
    }
    return cleaned;
  }

  async stop() {
    if (this.#child.exitCode !== null || this.#child.killed) return;
    this.#child.stdin.write('quit\n');
    await new Promise((resolveExit) => {
      const timer = setTimeout(() => { this.#child.kill('SIGKILL'); resolveExit(); }, 5_000);
      this.#child.once('exit', () => { clearTimeout(timer); resolveExit(); });
    });
  }

  #readPrompt(timeoutMs) {
    const boundary = this.#buffer.indexOf(PROMPT);
    if (boundary >= 0) return Promise.resolve(this.#consume(boundary));
    return Promise.race([
      new Promise((resolveValue, reject) => {
        const timer = setTimeout(() => {
          const index = this.#waiters.findIndex((item) => item.resolve === resolveValue);
          if (index >= 0) this.#waiters.splice(index, 1);
          reject(new Error(`Renode monitor timed out after ${timeoutMs} ms`));
        }, timeoutMs);
        this.#waiters.push({
          resolve: (value) => { clearTimeout(timer); resolveValue(value); },
          reject: (error) => { clearTimeout(timer); reject(error); },
        });
      }),
      this.#closed,
    ]);
  }

  #drain() {
    while (this.#waiters.length) {
      const boundary = this.#buffer.indexOf(PROMPT);
      if (boundary < 0) return;
      this.#waiters.shift()?.resolve(this.#consume(boundary));
    }
  }

  #consume(boundary) {
    const value = this.#buffer.slice(0, boundary);
    this.#buffer = this.#buffer.slice(boundary + PROMPT.length);
    return value;
  }
}

const monitor = new RenodeMonitor();
let shuttingDown = false;
let sweepSequence = 0;
let generator = {
  frequencyHz: 100_000_000,
  levelDbm: -30,
  path: 'mixer',
  modulation: 'off',
  modulationFrequencyHz: 1_000,
  amDepthPercent: 80,
  fmDeviationHz: 3_000,
  enabled: false,
};

try {
  const bootEvidence = await monitor.start();
  emit({
    type: 'ready',
    contractVersion: CONTRACT_VERSION,
    backend: 'renode-executable-twin',
    firmwareRelease: 'lab-v0.2.0-protocol',
    firmwareSourceCommit: 'd12bd826555eee51505542a55fd184ade5817d58',
    firmwareBinarySha256: 'a1dbaa03978a25b2a8b2a0e85f60029a6cc736481732eff68e93362724683dd7',
    usbTransactionsModeled: false,
    bridge: 'renode-monitor-v1',
    bootEvidence,
  });
} catch (error) {
  emit({ type: 'fatal', contractVersion: CONTRACT_VERSION, error: safeError(error) });
  await monitor.stop();
  process.exit(1);
}

const lines = createInterface({ input: process.stdin, crlfDelay: Infinity });
lines.on('line', (line) => void handleLine(line));
lines.on('close', () => void shutdown(0));
process.on('SIGINT', () => void shutdown(130));
process.on('SIGTERM', () => void shutdown(143));

let chain = Promise.resolve();
function handleLine(line) {
  chain = chain.then(async () => {
    if (Buffer.byteLength(line) > MAX_REQUEST_BYTES) throw new Error('Twin bridge request exceeds 64 KiB');
    let request;
    try { request = JSON.parse(line); }
    catch { throw new Error('Twin bridge request is not valid JSON'); }
    const input = object(request, 'Twin bridge request');
    const id = boundedString(input.id, 'request.id', 256);
    try {
      const result = await dispatch(input);
      emit({ id, ok: true, contractVersion: CONTRACT_VERSION, result });
    } catch (error) {
      emit({ id, ok: false, contractVersion: CONTRACT_VERSION, error: safeError(error) });
    }
  }).catch((error) => {
    emit({ type: 'fatal', contractVersion: CONTRACT_VERSION, error: safeError(error) });
    return shutdown(1);
  });
}

async function dispatch(request) {
  if (request.contractVersion !== CONTRACT_VERSION) throw new Error(`Twin bridge requires contractVersion ${CONTRACT_VERSION}`);
  const method = boundedString(request.method, 'request.method', 64);
  const params = request.params === undefined ? {} : object(request.params, 'request.params');
  if (method === 'status') return { report: requireLine(await monitor.command('twinStatus Report'), 'ZS407_TWIN_STATUS') };
  if (method === 'acquire_sweep') return acquireSweep(params);
  if (method === 'capture_screen') return captureScreen();
  if (method === 'configure_generator') return configureGenerator(params, false);
  if (method === 'set_generator_output') return setGeneratorOutput(params);
  if (method === 'touch') return touch(params);
  if (method === 'release_touch') return releaseTouch();
  if (method === 'shutdown') { setImmediate(() => void shutdown(0)); return { accepted: true }; }
  throw new Error(`Unknown twin bridge method ${method}`);
}

async function acquireSweep(params) {
  const startHz = safeInteger(params.startHz, 'startHz', 0, 17_922_600_000);
  const stopHz = safeInteger(params.stopHz, 'stopHz', startHz, 17_922_600_000);
  const points = safeInteger(params.points, 'points', MIN_POINTS, MAX_POINTS);
  const rbwKhz = autoOrNumber(params.rbwKhz, 'rbwKhz', 0.2, 850);
  const attenuationDb = autoOrNumber(params.attenuationDb, 'attenuationDb', 0, 31);
  const rbwX10 = rbwKhz === 'auto' ? 0 : Math.round(rbwKhz * 10);
  const attenuationX2 = attenuationDb === 'auto' ? 0 : Math.round(attenuationDb * 2);
  const sweepTimeSeconds = autoOrNumber(params.sweepTimeSeconds, 'sweepTimeSeconds', 0.003, 60);
  const detector = enumeration(params.detector, 'detector', ['sample', 'minimum-hold', 'maximum-hold', 'maximum-decay', 'average-4', 'average-16', 'average', 'quasi-peak']);
  const spurRejection = enumeration(params.spurRejection, 'spurRejection', ['off', 'on', 'auto']);
  const lna = enumeration(params.lna, 'lna', ['off', 'on']);
  const avoidSpurs = enumeration(params.avoidSpurs, 'avoidSpurs', ['off', 'on', 'auto']);
  const trigger = object(params.trigger, 'trigger');
  const triggerMode = enumeration(trigger.mode, 'trigger.mode', ['auto', 'normal', 'single']);
  const triggerLevelDbm = trigger.levelDbm === undefined ? -150 : finiteNumber(trigger.levelDbm, 'trigger.levelDbm', -174, 30);
  const sweepTimeUs = sweepTimeSeconds === 'auto' ? 0 : Math.round(sweepTimeSeconds * 1_000_000);
  const detectorIndex = ['sample', 'minimum-hold', 'maximum-hold', 'maximum-decay', 'average-4', 'average-16', 'average', 'quasi-peak'].indexOf(detector);
  const spurIndex = ['off', 'on', 'auto'].indexOf(spurRejection);
  const avoidIndex = ['auto', 'off', 'on'].indexOf(avoidSpurs);
  const triggerIndex = ['auto', 'normal', 'single'].indexOf(triggerMode);
  await monitor.command(`twinStatus ConfigureAnalyzer ${startHz} ${stopHz} ${points} ${rbwX10} ${attenuationX2} ${attenuationDb === 'auto' ? 1 : 0} ${sweepTimeUs} ${detectorIndex} ${spurIndex} ${lna === 'on' ? 1 : 0} ${avoidIndex} ${triggerIndex} ${triggerLevelDbm}`);
  await monitor.command('spi1.spiFabric.receiver ResetRssiStatistics');

  let sweepLine;
  for (let attempt = 0; attempt < 4; attempt++) {
    await monitor.command('emulation RunFor "0.5"', BOOT_TIMEOUT_MS);
    try { sweepLine = requireLine(await monitor.command('twinStatus ExportSweep'), 'ZS407_TWIN_SWEEP'); break; }
    catch (error) {
      if (!/has not completed/i.test(String(error)) || attempt === 3) throw error;
    }
  }
  if (!sweepLine) throw new Error('Twin sweep completed without export evidence');
  const fields = parseEvidence(sweepLine, 'ZS407_TWIN_SWEEP');
  const powerBytes = Buffer.from(requiredField(fields, 'power_f32le'), 'base64');
  if (powerBytes.length !== points * 4) throw new Error(`Twin sweep returned ${powerBytes.length} power bytes; expected ${points * 4}`);
  const powerDbm = Array.from({ length: points }, (_, index) => powerBytes.readFloatLE(index * 4));
  if (powerDbm.some((value) => !Number.isFinite(value))) throw new Error('Twin sweep contains non-finite power');
  return {
    kind: 'spectrum',
    sequence: ++sweepSequence,
    frequencyHz: ddaFrequencies(startHz, stopHz, points),
    powerDbm,
    actualRbwHz: Number(requiredField(fields, 'rbw_hz')),
    actualAttenuationDb: attenuationDb === 'auto' ? 0 : attenuationDb,
    evidence: 'firmware-executed-renode',
    bridgeEvidence: withoutPayload(sweepLine),
  };
}

async function captureScreen() {
  const directory = await mkdtemp(join(tmpdir(), 'tinysa-twin-'));
  const path = join(directory, 'screen.rgb565le');
  try {
    const output = await monitor.command(`twinStatus SaveScreenRaw "${path}"`);
    const evidence = requireLine(output, 'ZS407_TWIN_SCREEN=SAVED');
    const pixels = await readFile(path);
    if (pixels.length !== 480 * 320 * 2) throw new Error(`Twin screen contains ${pixels.length} bytes`);
    return { width: 480, height: 320, format: 'rgb565le', pixelsBase64: pixels.toString('base64'), evidence };
  } finally { await rm(directory, { recursive: true, force: true }); }
}

async function configureGenerator(params, preserveEnabled) {
  const next = {
    frequencyHz: safeInteger(params.frequencyHz, 'frequencyHz', 1, 17_922_600_000),
    levelDbm: finiteNumber(params.levelDbm, 'levelDbm', -115, -18.5),
    path: enumeration(params.path, 'path', ['normal', 'mixer']),
    modulation: enumeration(params.modulation, 'modulation', ['off', 'am', 'fm']),
    modulationFrequencyHz: safeInteger(params.modulationFrequencyHz, 'modulationFrequencyHz', 1, 10_000),
    amDepthPercent: safeInteger(params.amDepthPercent, 'amDepthPercent', 0, 100),
    fmDeviationHz: safeInteger(params.fmDeviationHz, 'fmDeviationHz', 1_000, 300_000),
    enabled: preserveEnabled ? generator.enabled : false,
  };
  const modulation = { off: 0, am: 1, fm: 2 }[next.modulation];
  const output = await monitor.command(`twinStatus ConfigureGenerator ${next.frequencyHz} ${next.levelDbm} ${next.path === 'mixer' ? 1 : 0} ${modulation} ${next.modulationFrequencyHz} ${next.amDepthPercent} ${next.fmDeviationHz} ${next.enabled ? 1 : 0}`);
  generator = next;
  return { configuration: { ...generator }, evidence: requireLine(output, 'ZS407_TWIN_GENERATOR=CONFIGURED') };
}

async function setGeneratorOutput(params) {
  const enabled = boolean(params.enabled, 'enabled');
  const next = await configureGenerator(generator, true);
  if (generator.enabled !== enabled) {
    generator.enabled = enabled;
    const modulation = { off: 0, am: 1, fm: 2 }[generator.modulation];
    const output = await monitor.command(`twinStatus ConfigureGenerator ${generator.frequencyHz} ${generator.levelDbm} ${generator.path === 'mixer' ? 1 : 0} ${modulation} ${generator.modulationFrequencyHz} ${generator.amDepthPercent} ${generator.fmDeviationHz} ${enabled ? 1 : 0}`);
    next.evidence = requireLine(output, 'ZS407_TWIN_GENERATOR=CONFIGURED');
  }
  await monitor.command('emulation RunFor "0.3"', BOOT_TIMEOUT_MS);
  return { enabled, configuration: { ...generator }, evidence: next.evidence, report: requireLine(await monitor.command('twinStatus Report'), 'ZS407_TWIN_STATUS') };
}

async function touch(params) {
  const x = safeInteger(params.x, 'x', 0, 479);
  const y = safeInteger(params.y, 'y', 0, 319);
  await monitor.command(`adc2 SetTouchPixel ${x} ${y}`);
  await monitor.command('emulation RunFor "0.3"', BOOT_TIMEOUT_MS);
  return { x, y, evidence: requireLine(await monitor.command('twinStatus AssertTouchAccepted'), 'ZS407_TWIN_TOUCH=PASS') };
}

async function releaseTouch() {
  await monitor.command('adc2 ReleaseTouch');
  await monitor.command('emulation RunFor "0.1"', BOOT_TIMEOUT_MS);
  return { released: true };
}

async function shutdown(code) {
  if (shuttingDown) return;
  shuttingDown = true;
  lines.close();
  await monitor.stop();
  process.exitCode = code;
}

function ddaFrequencies(start, stop, points) {
  const count = points - 1;
  const span = stop - start;
  const delta = Math.floor(span / count);
  const error = span % count;
  return Array.from({ length: points }, (_, index) => start + delta * index + Math.floor((Math.floor(count / 2) + error * index) / count));
}
function emit(value) { process.stdout.write(`${JSON.stringify(value)}\n`); }
function object(value, label) { if (!value || typeof value !== 'object' || Array.isArray(value)) throw new TypeError(`${label} must be an object`); return value; }
function boundedString(value, label, maximum) { if (typeof value !== 'string' || !value || value.length > maximum) throw new TypeError(`${label} must be a bounded string`); return value; }
function safeInteger(value, label, minimum, maximum) { if (!Number.isSafeInteger(value) || value < minimum || value > maximum) throw new RangeError(`${label} must be an integer in ${minimum}..${maximum}`); return value; }
function finiteNumber(value, label, minimum, maximum) { if (typeof value !== 'number' || !Number.isFinite(value) || value < minimum || value > maximum) throw new RangeError(`${label} must be in ${minimum}..${maximum}`); return value; }
function autoOrNumber(value, label, minimum, maximum) { return value === 'auto' ? value : finiteNumber(value, label, minimum, maximum); }
function boolean(value, label) { if (typeof value !== 'boolean') throw new TypeError(`${label} must be boolean`); return value; }
function enumeration(value, label, values) { if (typeof value !== 'string' || !values.includes(value)) throw new TypeError(`${label} must be one of ${values.join(', ')}`); return value; }
function requireLine(output, prefix) { const line = output.split('\n').map((item) => item.trim()).find((item) => item.startsWith(prefix)); if (!line) throw new Error(`Renode output omitted ${prefix}: ${singleLine(output)}`); return line; }
function parseEvidence(line, prefix) { const fields = new Map(); for (const token of line.slice(prefix.length).trim().split(/\s+/)) { const index = token.indexOf('='); if (index > 0) fields.set(token.slice(0, index), token.slice(index + 1)); } return fields; }
function requiredField(fields, name) { const value = fields.get(name); if (value === undefined) throw new Error(`Twin evidence omitted ${name}`); return value; }
function withoutPayload(line) { return line.replace(/\s+power_f32le=\S+/, ' power_f32le=<redacted>'); }
function cleanMonitorOutput(raw, command) { return raw.replace(/\x1B\[[0-?]*[ -/]*[@-~]/g, '').replace(/\r/g, '').split('\n').filter((line, index) => !(index === 0 && line.trim() === command.trim())).join('\n').trim(); }
function singleLine(value) { return String(value).replace(/[\r\n\t]+/g, ' ').replace(/\s+/g, ' ').trim().slice(0, 1_000); }
function safeError(error) { return { code: 'twin-bridge-failure', message: singleLine(error instanceof Error ? error.message : error) }; }
