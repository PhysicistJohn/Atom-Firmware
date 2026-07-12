// SPDX-License-Identifier: GPL-3.0-or-later
import Foundation

private enum TestFailure: Error {
    case mismatch(String)
}

private func fixture(_ directory: String, _ name: String) throws -> [UInt8] {
    let path = URL(fileURLWithPath: directory)
        .appendingPathComponent("protocol_v2_\(name).hex")
    let text = try String(contentsOf: path, encoding: .utf8)
    return text.split(separator: "\n")
        .filter { !$0.trimmingCharacters(in: .whitespaces).hasPrefix("#") }
        .flatMap { $0.split(whereSeparator: { $0.isWhitespace }) }
        .compactMap { UInt8($0, radix: 16) }
}

private func require(_ condition: @autoclosure () -> Bool,
                     _ message: String) throws {
    if !condition() { throw TestFailure.mismatch(message) }
}

@main
private struct ContractTest {
    static func main() throws {
        guard CommandLine.arguments.count == 2 else {
            throw TestFailure.mismatch("fixture directory argument")
        }
        let directory = CommandLine.arguments[1]
        let capabilities = ZS407Contract.CapabilitiesPayload(
            schemaVersion: 2, protocolVersion: 2, releasePhase: 6, profileId: 1,
            featureBits: 0x12345678, safetyBits: 0x89abcdef,
            maximumPayloadBytes: 1024, maximumTracePoints: 4096,
            maximumSweepPoints: 450, maximumFftPoints: 1024,
            waveformSampleCount: 256, waveformEventBytes: 16)
        let capabilitiesFixture = try fixture(directory, "capabilities")
        try require(capabilities.encode() == capabilitiesFixture,
                    "capabilities bytes")
        try require(ZS407Contract.CapabilitiesPayload(
            wireBytes: capabilities.encode()) == capabilities,
                    "capabilities round trip")

        let trace = ZS407Contract.TraceChunkPayload(
            traceId: 0x10203040, sequence: 3, flags: 1,
            startIndex: 900, pointCount: 450, totalPoints: 4096,
            validityBytes: 57, startHz: 1_000_000_000,
            frequencyStepNumeratorHz: 1_234_567_890_123,
            frequencyStepDenominator: 4095, rbwHz: 10_000, enbwHz: 11_200,
            timestampUs: 0x0102030405060708, path: 2, detector: 4,
            powerScaleDb: 32, reserved: 0)
        let traceFixture = try fixture(directory, "trace_chunk")
        try require(trace.encode() == traceFixture,
                    "trace bytes")
        try require(ZS407Contract.TraceChunkPayload(
            wireBytes: trace.encode()) == trace, "trace round trip")

        let upload = ZS407Contract.WaveformUploadPayload(
            programId: 407, uncompressedBytes: 96, crc32: 0xcbf43926,
            eventCount: 6, encoding: 1, flags: 0)
        let uploadFixture = try fixture(directory, "waveform_upload")
        try require(upload.encode() == uploadFixture,
                    "waveform bytes")

        let status = ZS407Contract.StatusPayload(
            status: 5, reserved: 0, detail: 0x1234)
        let statusFixture = try fixture(directory, "status")
        try require(status.encode() == statusFixture,
                    "status bytes")
        print("ZS407 Swift contract: passed")
    }
}
