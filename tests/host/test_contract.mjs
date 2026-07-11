// SPDX-License-Identifier: GPL-3.0-or-later
import { readFileSync } from "node:fs";
import {
  encodeCapabilitiesPayload,
  decodeCapabilitiesPayload,
  encodeTraceChunkPayload,
  decodeTraceChunkPayload,
  encodeWaveformUploadPayload,
  encodeStatusPayload,
} from "../../modern/generated/zs407-contract.mjs";

function fixture(directory, name) {
  return Uint8Array.from(
    readFileSync(`${directory}/protocol_v2_${name}.hex`, "utf8")
      .split("\n")
      .filter((line) => !line.trimStart().startsWith("#"))
      .join(" ")
      .trim()
      .split(/\s+/)
      .filter(Boolean)
      .map((value) => Number.parseInt(value, 16)),
  );
}

function requireEqual(actual, expected, message) {
  if (actual.length !== expected.length ||
      actual.some((value, index) => value !== expected[index])) {
    throw new Error(message);
  }
}

const directory = process.argv[2];
if (!directory) throw new Error("fixture directory argument");

const capabilities = {
  schemaVersion: 2,
  protocolVersion: 2,
  releasePhase: 6,
  profileId: 1,
  featureBits: 0x12345678,
  safetyBits: 0x89abcdef,
  maximumPayloadBytes: 1024,
  maximumTracePoints: 4096,
  maximumSweepPoints: 450,
  maximumFftPoints: 512,
  waveformSampleCount: 256,
  waveformEventBytes: 16,
};
const capabilityBytes = encodeCapabilitiesPayload(capabilities);
requireEqual(capabilityBytes, fixture(directory, "capabilities"),
             "capabilities bytes");
if (JSON.stringify(decodeCapabilitiesPayload(capabilityBytes)) !==
    JSON.stringify(capabilities)) throw new Error("capabilities round trip");

const trace = {
  traceId: 0x10203040,
  sequence: 3,
  flags: 1,
  startIndex: 900,
  pointCount: 450,
  totalPoints: 4096,
  validityBytes: 57,
  startHz: 1_000_000_000n,
  frequencyStepNumeratorHz: 1_234_567_890_123n,
  frequencyStepDenominator: 4095,
  rbwHz: 10_000,
  enbwHz: 11_200,
  timestampUs: 0x0102030405060708n,
  path: 2,
  detector: 4,
  powerScaleDb: 32,
  reserved: 0,
};
const traceBytes = encodeTraceChunkPayload(trace);
requireEqual(traceBytes, fixture(directory, "trace_chunk"), "trace bytes");
const traceCopy = decodeTraceChunkPayload(traceBytes);
if (traceCopy.timestampUs !== trace.timestampUs ||
    traceCopy.frequencyStepNumeratorHz !== trace.frequencyStepNumeratorHz) {
  throw new Error("trace round trip");
}

requireEqual(encodeWaveformUploadPayload({
  programId: 407, uncompressedBytes: 96, crc32: 0xcbf43926,
  eventCount: 6, encoding: 1, flags: 0,
}), fixture(directory, "waveform_upload"), "waveform bytes");
requireEqual(encodeStatusPayload({ status: 5, reserved: 0, detail: 0x1234 }),
             fixture(directory, "status"), "status bytes");
console.log("ZS407 JavaScript contract: passed");
