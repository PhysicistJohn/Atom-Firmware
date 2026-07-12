// SPDX-License-Identifier: GPL-3.0-or-later
import { readFileSync } from "node:fs";
import {
  encodeCapabilitiesPayload,
  decodeCapabilitiesPayload,
  encodeTraceChunkPayload,
  decodeTraceChunkPayload,
  encodeClockSnapshotPayload,
  decodeClockSnapshotPayload,
  encodeAcquisitionStatusPayload,
  decodeAcquisitionStatusPayload,
  encodeAdaptiveWindowPayload,
  decodeAdaptiveWindowPayload,
  encodeCaptureSummaryPayload,
  decodeCaptureSummaryPayload,
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
  schemaVersion: 3,
  protocolVersion: 2,
  releasePhase: 6,
  profileId: 1,
  featureBits: 0x12345678,
  safetyBits: 0x89abcdef,
  maximumPayloadBytes: 1024,
  maximumTracePoints: 4096,
  maximumSweepPoints: 450,
  maximumFftPoints: 1024,
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

const clock = {
  clockId: 407, flags: 3, timestampUs: 0x0102030405060708n,
  tickFrequencyHz: 100_000, rawTick: 0x89abcdef,
};
const clockBytes = encodeClockSnapshotPayload(clock);
requireEqual(clockBytes, fixture(directory, "clock_snapshot"), "clock bytes");
if (JSON.stringify(decodeClockSnapshotPayload(clockBytes), (_, value) =>
  typeof value === "bigint" ? value.toString() : value) !==
    JSON.stringify(clock, (_, value) =>
      typeof value === "bigint" ? value.toString() : value)) {
  throw new Error("clock round trip");
}

const acquisition = {
  streamId: 0x11223344, nextSequence: 0x55667788,
  completedSweeps: 1000, publishedSweeps: 997, droppedSweeps: 2,
  invalidSweeps: 1, lastStartUs: 123_456_789_012_345n,
  lastDurationUs: 45_678, lastPointCount: 450, state: 2, flags: 5,
};
const acquisitionBytes = encodeAcquisitionStatusPayload(acquisition);
requireEqual(acquisitionBytes, fixture(directory, "acquisition_status"),
             "acquisition bytes");
if (decodeAcquisitionStatusPayload(acquisitionBytes).lastStartUs !==
    acquisition.lastStartUs) throw new Error("acquisition round trip");

const adaptive = {
  planId: 407, sourceTraceId: 408, firstIndex: 100, lastIndex: 140,
  peakIndex: 123, priority: 17, startHz: 915_000_000n,
  stopHz: 916_000_000n, pointCount: 201, flags: 1,
};
const adaptiveBytes = encodeAdaptiveWindowPayload(adaptive);
requireEqual(adaptiveBytes, fixture(directory, "adaptive_window"),
             "adaptive bytes");
if (decodeAdaptiveWindowPayload(adaptiveBytes).stopHz !== adaptive.stopHz) {
  throw new Error("adaptive round trip");
}

const capture = {
  captureId: 1024, sequence: 7, flags: 11, sampleCount: 1024,
  triggerIndex: 256, peakBin: 73, reserved: 0,
  firstTimestampUs: 1_000_000n, lastTimestampUs: 2_023_000n,
  samplePeriodNs: 1_000_000, minimumDeltaUs: 998,
  maximumDeltaUs: 1004, discontinuities: 0, peakMagnitudeQ30: 536_870_912,
};
const captureBytes = encodeCaptureSummaryPayload(capture);
requireEqual(captureBytes, fixture(directory, "capture_summary"),
             "capture bytes");
if (decodeCaptureSummaryPayload(captureBytes).peakBin !== 73) {
  throw new Error("capture round trip");
}

requireEqual(encodeWaveformUploadPayload({
  programId: 407, uncompressedBytes: 96, crc32: 0xcbf43926,
  eventCount: 6, encoding: 1, flags: 0,
}), fixture(directory, "waveform_upload"), "waveform bytes");
requireEqual(encodeStatusPayload({ status: 5, reserved: 0, detail: 0x1234 }),
             fixture(directory, "status"), "status bytes");
console.log("ZS407 JavaScript contract: passed");
