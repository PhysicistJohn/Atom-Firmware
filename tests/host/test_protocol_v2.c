/* SPDX-License-Identifier: GPL-3.0-or-later */
#include "modern/core/zs407_capabilities.h"
#include "modern/core/zs407_compact.h"
#include "modern/core/zs407_protocol.h"
#include "modern/core/zs407_spsc.h"
#include "modern/core/zs407_trace_codec.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define CHECK(condition)                                                       \
  do {                                                                         \
    if (!(condition)) {                                                        \
      fprintf(stderr, "CHECK failed at %s:%d: %s\n", __FILE__, __LINE__,      \
              #condition);                                                     \
      return 1;                                                                \
    }                                                                          \
  } while (0)

static size_t read_hex_fixture(const char *path, uint8_t *output,
                               size_t capacity)
{
  FILE *stream = fopen(path, "r");
  if (stream == NULL) {
    return 0U;
  }
  size_t count = 0U;
  char line[256];
  while (fgets(line, sizeof(line), stream) != NULL) {
    char *cursor = line;
    while (*cursor != '\0' && *cursor != '#') {
      unsigned value = 0U;
      int consumed = 0;
      if (sscanf(cursor, " %2x%n", &value, &consumed) == 1) {
        if (count >= capacity) {
          fclose(stream);
          return 0U;
        }
        output[count++] = (uint8_t)value;
        cursor += consumed;
      } else {
        ++cursor;
      }
    }
  }
  fclose(stream);
  return count;
}

static int fixture_path(char *output, size_t capacity, const char *directory,
                        const char *name)
{
  int length = snprintf(output, capacity, "%s/protocol_v2_%s.hex",
                        directory, name);
  return length > 0 && (size_t)length < capacity ? 0 : 1;
}

static int test_generated_payloads(const char *fixture_directory)
{
  uint8_t actual[128];
  uint8_t expected[128];
  char path[512];

  zs407_capabilities_payload_t capabilities = {
      3U, 2U, 6U, 1U, UINT32_C(0x12345678), UINT32_C(0x89abcdef),
      1024U, 4096U, 450U, 1024U, 256U, 16U};
  CHECK(zs407_capabilities_payload_encode(
      &capabilities, actual, ZS407_CAPABILITIES_PAYLOAD_BYTES));
  CHECK(fixture_path(path, sizeof(path), fixture_directory,
                     "capabilities") == 0);
  size_t expected_length = read_hex_fixture(path, expected, sizeof(expected));
  CHECK(expected_length == ZS407_CAPABILITIES_PAYLOAD_BYTES);
  CHECK(memcmp(actual, expected, expected_length) == 0);
  zs407_capabilities_payload_t capabilities_copy;
  CHECK(zs407_capabilities_payload_decode(actual, sizeof(capabilities),
                                           &capabilities_copy));
  CHECK(capabilities_copy.feature_bits == capabilities.feature_bits);
  CHECK(capabilities_copy.safety_bits == capabilities.safety_bits);
  CHECK(capabilities_copy.waveform_event_bytes == 16U);

  zs407_clock_snapshot_payload_t clock = {
      407U, 3U, UINT64_C(0x0102030405060708), 100000U,
      UINT32_C(0x89abcdef)};
  CHECK(zs407_clock_snapshot_payload_encode(
      &clock, actual, ZS407_CLOCK_SNAPSHOT_PAYLOAD_BYTES));
  CHECK(fixture_path(path, sizeof(path), fixture_directory,
                     "clock_snapshot") == 0);
  expected_length = read_hex_fixture(path, expected, sizeof(expected));
  CHECK(expected_length == ZS407_CLOCK_SNAPSHOT_PAYLOAD_BYTES);
  CHECK(memcmp(actual, expected, expected_length) == 0);

  zs407_acquisition_status_payload_t acquisition = {
      UINT32_C(0x11223344), UINT32_C(0x55667788), 1000U, 997U, 2U, 1U,
      UINT64_C(123456789012345), 45678U, 450U, 2U, 5U};
  CHECK(zs407_acquisition_status_payload_encode(
      &acquisition, actual, ZS407_ACQUISITION_STATUS_PAYLOAD_BYTES));
  CHECK(fixture_path(path, sizeof(path), fixture_directory,
                     "acquisition_status") == 0);
  expected_length = read_hex_fixture(path, expected, sizeof(expected));
  CHECK(expected_length == ZS407_ACQUISITION_STATUS_PAYLOAD_BYTES);
  CHECK(memcmp(actual, expected, expected_length) == 0);

  zs407_adaptive_window_payload_t adaptive = {
      407U, 408U, 100U, 140U, 123U, 17U, UINT64_C(915000000),
      UINT64_C(916000000), 201U, 1U};
  CHECK(zs407_adaptive_window_payload_encode(
      &adaptive, actual, ZS407_ADAPTIVE_WINDOW_PAYLOAD_BYTES));
  CHECK(fixture_path(path, sizeof(path), fixture_directory,
                     "adaptive_window") == 0);
  expected_length = read_hex_fixture(path, expected, sizeof(expected));
  CHECK(expected_length == ZS407_ADAPTIVE_WINDOW_PAYLOAD_BYTES);
  CHECK(memcmp(actual, expected, expected_length) == 0);

  zs407_capture_summary_payload_t capture = {
      1024U, 7U, 11U, 1024U, 256U, 73U, 0U, UINT64_C(1000000),
      UINT64_C(2023000), 1000000U, 998U, 1004U, 0U,
      UINT32_C(536870912)};
  CHECK(zs407_capture_summary_payload_encode(
      &capture, actual, ZS407_CAPTURE_SUMMARY_PAYLOAD_BYTES));
  CHECK(fixture_path(path, sizeof(path), fixture_directory,
                     "capture_summary") == 0);
  expected_length = read_hex_fixture(path, expected, sizeof(expected));
  CHECK(expected_length == ZS407_CAPTURE_SUMMARY_PAYLOAD_BYTES);
  CHECK(memcmp(actual, expected, expected_length) == 0);

  zs407_trace_chunk_payload_t trace = {
      UINT32_C(0x10203040), 3U, 1U, 900U, 450U, 4096U, 57U,
      UINT64_C(1000000000), UINT64_C(1234567890123), 4095U,
      10000U, 11200U, UINT64_C(0x0102030405060708), 2U, 4U, 32U, 0U};
  CHECK(zs407_trace_chunk_payload_encode(
      &trace, actual, ZS407_TRACE_CHUNK_PAYLOAD_BYTES));
  CHECK(fixture_path(path, sizeof(path), fixture_directory,
                     "trace_chunk") == 0);
  expected_length = read_hex_fixture(path, expected, sizeof(expected));
  CHECK(expected_length == ZS407_TRACE_CHUNK_PAYLOAD_BYTES);
  CHECK(memcmp(actual, expected, expected_length) == 0);
  zs407_trace_chunk_payload_t trace_copy;
  CHECK(zs407_trace_chunk_payload_decode(actual, expected_length,
                                          &trace_copy));
  CHECK(trace_copy.timestamp_us == trace.timestamp_us);
  CHECK(trace_copy.frequency_step_numerator_hz ==
        trace.frequency_step_numerator_hz);

  zs407_waveform_upload_payload_t upload = {
      407U, 96U, UINT32_C(0xcbf43926), 6U, 1U, 0U};
  CHECK(zs407_waveform_upload_payload_encode(
      &upload, actual, ZS407_WAVEFORM_UPLOAD_PAYLOAD_BYTES));
  CHECK(fixture_path(path, sizeof(path), fixture_directory,
                     "waveform_upload") == 0);
  expected_length = read_hex_fixture(path, expected, sizeof(expected));
  CHECK(expected_length == ZS407_WAVEFORM_UPLOAD_PAYLOAD_BYTES);
  CHECK(memcmp(actual, expected, expected_length) == 0);

  zs407_status_payload_t status = {5U, 0U, 0x1234U};
  CHECK(zs407_status_payload_encode(
      &status, actual, ZS407_STATUS_PAYLOAD_BYTES));
  CHECK(fixture_path(path, sizeof(path), fixture_directory, "status") == 0);
  expected_length = read_hex_fixture(path, expected, sizeof(expected));
  CHECK(expected_length == ZS407_STATUS_PAYLOAD_BYTES);
  CHECK(memcmp(actual, expected, expected_length) == 0);
  return 0;
}

typedef struct {
  uint8_t data[ZS407_FRAME_MAX_BYTES];
  size_t used;
} sink_capture_t;

static zs407_core_status_t capture_sink(void *context, const uint8_t *data,
                                        size_t length)
{
  sink_capture_t *capture = (sink_capture_t *)context;
  if (capture->used + length > sizeof(capture->data)) {
    return ZS407_CORE_BUFFER_TOO_SMALL;
  }
  memcpy(&capture->data[capture->used], data, length);
  capture->used += length;
  return ZS407_CORE_OK;
}

typedef struct {
  uint32_t count;
  uint16_t request_ids[8];
  uint16_t payload_lengths[8];
  uint32_t payload_crc[8];
} parser_capture_t;

static void capture_parser_frame(void *context, const zs407_frame_t *frame)
{
  parser_capture_t *capture = (parser_capture_t *)context;
  if (capture->count < 8U) {
    capture->request_ids[capture->count] = frame->request_id;
    capture->payload_lengths[capture->count] = frame->payload_length;
    capture->payload_crc[capture->count] =
        zs407_crc32(frame->payload, frame->payload_length);
  }
  capture->count++;
}

static int test_protocol_streaming(void)
{
  uint8_t output[ZS407_FRAME_MAX_BYTES];
  uint8_t payload[100];
  for (size_t i = 0U; i < sizeof(payload); ++i) {
    payload[i] = (uint8_t)(i * 7U);
  }
  zs407_frame_t frame = {
      .version = 2U, .flags = 0xa5U, .request_id = 407U,
      .command = ZS407_COMMAND_PING, .payload = payload,
      .payload_length = sizeof(payload)};
  size_t output_length = 0U;
  CHECK(zs407_frame_encode(&frame, output, sizeof(output),
                           &output_length) == ZS407_CORE_OK);
  CHECK(output_length == sizeof(payload) + ZS407_FRAME_OVERHEAD_BYTES);
  zs407_frame_t decoded;
  CHECK(zs407_frame_decode(output, output_length, &decoded) == ZS407_CORE_OK);
  CHECK(decoded.version == 2U && decoded.request_id == 407U);
  CHECK(memcmp(decoded.payload, payload, sizeof(payload)) == 0);

  zs407_frame_t in_place = frame;
  in_place.payload = NULL;
  in_place.payload_length = 31U;
  uint8_t *reserved = NULL;
  CHECK(zs407_frame_begin(&in_place, output, sizeof(output), &reserved) ==
        ZS407_CORE_OK);
  for (uint16_t i = 0U; i < in_place.payload_length; ++i) {
    reserved[i] = (uint8_t)(0xf0U ^ i);
  }
  CHECK(zs407_frame_finish(output, sizeof(output), &output_length) ==
        ZS407_CORE_OK);
  CHECK(zs407_frame_decode(output, output_length, &decoded) == ZS407_CORE_OK);
  CHECK(decoded.payload[30] == (uint8_t)(0xf0U ^ 30U));

  static const uint8_t first[] = {1U, 2U, 3U};
  static const uint8_t second[] = {4U, 5U, 6U, 7U};
  const zs407_bytes_t segments[] = {
      {NULL, 0U}, {first, sizeof(first)}, {second, sizeof(second)}};
  sink_capture_t sink = {{0}, 0U};
  frame.payload = NULL;
  frame.payload_length = 0U;
  CHECK(zs407_frame_write_segments(&frame, segments, 3U, capture_sink,
                                    &sink, &output_length) == ZS407_CORE_OK);
  CHECK(sink.used == 7U + ZS407_FRAME_OVERHEAD_BYTES);
  CHECK(zs407_frame_decode(sink.data, sink.used, &decoded) == ZS407_CORE_OK);
  CHECK(memcmp(decoded.payload, "\1\2\3\4\5\6\7", 7U) == 0);
  CHECK(zs407_frame_encode_segments(&frame, segments, 3U, output,
                                     sizeof(output), &output_length) ==
        ZS407_CORE_OK);
  CHECK(output_length == sink.used &&
        memcmp(output, sink.data, sink.used) == 0);

  uint8_t parser_storage[ZS407_FRAME_MAX_BYTES];
  zs407_stream_parser_t parser;
  CHECK(zs407_stream_parser_init(&parser, parser_storage,
                                  sizeof(parser_storage)) == ZS407_CORE_OK);
  parser_capture_t capture = {0};
  uint8_t stream[512];
  size_t stream_length = 0U;
  const uint8_t noise[] = {0xaaU, 0x53U, 0x00U, 0xbbU};
  memcpy(stream, noise, sizeof(noise));
  stream_length += sizeof(noise);
  memcpy(&stream[stream_length], sink.data, sink.used);
  stream_length += sink.used;
  memcpy(&stream[stream_length], output, output_length);
  stream_length += output_length;
  for (size_t offset = 0U; offset < stream_length;) {
    size_t count = (offset % 23U) + 1U;
    if (count > stream_length - offset) {
      count = stream_length - offset;
    }
    size_t accepted = 0U;
    CHECK(zs407_stream_parser_feed(
        &parser, &stream[offset], count, capture_parser_frame,
        &capture, &accepted) == ZS407_CORE_OK);
    offset += count;
  }
  CHECK(capture.count == 2U);
  CHECK(capture.request_ids[0] == 407U && capture.request_ids[1] == 407U);
  CHECK(parser.accepted_frames == 2U && parser.rejected_frames == 0U);
  CHECK(parser.discarded_bytes == sizeof(noise));

  sink.data[10] ^= 1U;
  size_t accepted = 0U;
  CHECK(zs407_stream_parser_feed(&parser, sink.data, sink.used,
                                  capture_parser_frame, &capture,
                                  &accepted) == ZS407_CORE_OK);
  CHECK(accepted == 0U && parser.rejected_frames == 1U);
  CHECK(zs407_stream_parser_feed(&parser, output, output_length,
                                  capture_parser_frame, &capture,
                                  &accepted) == ZS407_CORE_OK);
  CHECK(accepted == 1U && capture.count == 3U);

  uint8_t overlapped[ZS407_FRAME_MAX_BYTES + 3U];
  overlapped[0] = (uint8_t)ZS407_PROTOCOL_MAGIC;
  overlapped[1] = (uint8_t)(ZS407_PROTOCOL_MAGIC >> 8);
  overlapped[2] = 0xffU;
  memcpy(&overlapped[3], output, output_length);
  CHECK(zs407_stream_parser_feed(
      &parser, overlapped, output_length + 3U, capture_parser_frame,
      &capture, &accepted) == ZS407_CORE_OK);
  CHECK(accepted == 1U && capture.count == 4U);

  zs407_crc32_context_t crc;
  zs407_crc32_init(&crc);
  zs407_crc32_update(&crc, (const uint8_t *)"1234", 4U);
  zs407_crc32_update(&crc, (const uint8_t *)"56789", 5U);
  CHECK(zs407_crc32_final(&crc) == UINT32_C(0xcbf43926));
  return 0;
}

static int test_trace_chunks(void)
{
  CHECK(zs407_trace_chunk_payload_size(450U) == 1013U);
  CHECK(zs407_trace_chunk_payload_size(451U) == 0U);
  uint8_t payload[ZS407_PROTOCOL_MAX_PAYLOAD];
  zs407_db32_t samples[ZS407_PROTOCOL_MAX_TRACE_CHUNK_POINTS];
  uint16_t start = 0U;
  uint16_t sequence = 0U;
  while (start < ZS407_PROTOCOL_MAX_TRACE_POINTS) {
    uint16_t count = (uint16_t)(ZS407_PROTOCOL_MAX_TRACE_POINTS - start);
    if (count > ZS407_PROTOCOL_MAX_TRACE_CHUNK_POINTS) {
      count = ZS407_PROTOCOL_MAX_TRACE_CHUNK_POINTS;
    }
    for (uint16_t i = 0U; i < count; ++i) {
      samples[i] = ((start + i) % 17U) == 0U
                       ? ZS407_TRACE_INVALID_SAMPLE
                       : (zs407_db32_t)(-3200 + (int32_t)(start + i) / 2);
    }
    zs407_trace_chunk_payload_t header = {
        .trace_id = 0x407U,
        .sequence = sequence,
        .flags = start + count == ZS407_PROTOCOL_MAX_TRACE_POINTS ? 1U : 0U,
        .start_index = start,
        .point_count = count,
        .total_points = ZS407_PROTOCOL_MAX_TRACE_POINTS,
        .validity_bytes = 0U,
        .start_hz = UINT64_C(1000000000),
        .frequency_step_numerator_hz = UINT64_C(100000003),
        .frequency_step_denominator = 4095U,
        .rbw_hz = 10000U,
        .enbw_hz = 11200U,
        .timestamp_us = UINT64_C(123456789) + sequence,
        .path = 2U,
        .detector = 1U,
        .power_scale_db = ZS407_TRACE_DB_SCALE,
        .reserved = 0U};
    size_t payload_length = 0U;
    CHECK(zs407_trace_chunk_encode(&header, samples, payload,
                                    sizeof(payload), &payload_length) ==
          ZS407_CORE_OK);
    CHECK(payload_length <= ZS407_PROTOCOL_MAX_PAYLOAD);
    zs407_trace_chunk_view_t view;
    CHECK(zs407_trace_chunk_decode(payload, payload_length, &view) ==
          ZS407_CORE_OK);
    CHECK(view.header.start_index == start && view.header.point_count == count);
    for (uint16_t i = 0U; i < count; ++i) {
      CHECK(zs407_trace_chunk_point(&view, i) == samples[i]);
      CHECK(zs407_trace_chunk_point_valid(&view, i) ==
            (samples[i] != ZS407_TRACE_INVALID_SAMPLE));
    }
    if ((count & 7U) != 0U) {
      payload[payload_length - 1U] |= 0x80U;
      CHECK(zs407_trace_chunk_decode(payload, payload_length, &view) ==
            ZS407_CORE_BAD_FRAME);
    }
    start = (uint16_t)(start + count);
    sequence++;
  }
  CHECK(sequence == 10U);
  return 0;
}

static int test_compact_codecs(void)
{
  const uint64_t values[] = {0U, 1U, 127U, 128U, 16384U, UINT64_MAX};
  for (size_t i = 0U; i < sizeof(values) / sizeof(values[0]); ++i) {
    uint8_t encoded[10];
    size_t length = 0U;
    CHECK(zs407_uleb128_encode(values[i], encoded, sizeof(encoded),
                               &length) == ZS407_CORE_OK);
    uint64_t decoded = 0U;
    size_t consumed = 0U;
    CHECK(zs407_uleb128_decode(encoded, length, &decoded, &consumed) ==
          ZS407_CORE_OK);
    CHECK(decoded == values[i] && consumed == length);
  }

  zs407_db32_t samples[450];
  zs407_db32_t decoded_samples[450];
  for (size_t i = 0U; i < 450U; ++i) {
    samples[i] = (zs407_db32_t)(-3000 + (int32_t)(i / 7U));
  }
  uint8_t compact[1350];
  size_t compact_length = 0U;
  CHECK(zs407_trace_delta_encode(samples, 450U, compact, sizeof(compact),
                                  &compact_length) == ZS407_CORE_OK);
  CHECK(compact_length < sizeof(samples));
  CHECK(zs407_trace_delta_decode(compact, compact_length, decoded_samples,
                                  450U) == ZS407_CORE_OK);
  CHECK(memcmp(samples, decoded_samples, sizeof(samples)) == 0);

  const zs407_wave_event_t program[] = {
      {0U, ZS407_EVENT_GATE, 0U, 0U, 0},
      {0U, ZS407_EVENT_SET_FREQUENCY_HZ, 0U, 0U, 100000000},
      {0U, ZS407_EVENT_SET_LEVEL_DBM_X10, 0U, 0U, -300},
      {1000U, ZS407_EVENT_GATE, 0U, 0U, 1},
      {11000U, ZS407_EVENT_GATE, 0U, 0U, 0},
      {11000U, ZS407_EVENT_END, 0U, 0U, 0}};
  zs407_wave_event_t decoded_program[6];
  CHECK(zs407_wave_events_compact_encode(
      program, 6U, compact, sizeof(compact), &compact_length) ==
        ZS407_CORE_OK);
  CHECK(compact_length < sizeof(program));
  CHECK(zs407_wave_events_compact_decode(
      compact, compact_length, decoded_program, 6U) == ZS407_CORE_OK);
  CHECK(memcmp(program, decoded_program, sizeof(program)) == 0);
  return 0;
}

static int test_spsc(void)
{
  uint8_t storage[8];
  zs407_spsc_ring_t ring;
  CHECK(zs407_spsc_ring_init(&ring, storage, sizeof(storage)) ==
        ZS407_CORE_OK);
  static const uint8_t first[] = {0U, 1U, 2U, 3U, 4U, 5U};
  static const uint8_t second[] = {6U, 7U, 8U, 9U, 10U, 11U};
  uint8_t output[8];
  CHECK(zs407_spsc_ring_write(&ring, first, sizeof(first)) == sizeof(first));
  CHECK(zs407_spsc_ring_read(&ring, output, 4U) == 4U);
  CHECK(memcmp(output, first, 4U) == 0);
  CHECK(zs407_spsc_ring_write(&ring, second, sizeof(second)) ==
        sizeof(second));
  CHECK(zs407_spsc_ring_available(&ring) == 8U);
  CHECK(zs407_spsc_ring_free(&ring) == 0U);
  CHECK(zs407_spsc_ring_read(&ring, output, sizeof(output)) ==
        sizeof(output));
  static const uint8_t expected[] = {4U, 5U, 6U, 7U, 8U, 9U, 10U, 11U};
  CHECK(memcmp(output, expected, sizeof(expected)) == 0);
  return 0;
}

static int test_release_profile(void)
{
  zs407_release_manifest_t manifest;
  CHECK(zs407_capabilities_selftest() == 0U);
  CHECK(zs407_release_manifest_for_phase(6U, &manifest) == ZS407_CORE_OK);
  CHECK((manifest.feature_bits & ZS407_CAP_TYPED_PROTOCOL_V2) != 0U);
  CHECK((manifest.feature_bits & ZS407_CAP_STREAMING_MARSHALLING) != 0U);
  CHECK((manifest.feature_bits & ZS407_CAP_COMPACT_STORAGE_CODECS) != 0U);
  CHECK((manifest.feature_bits & ZS407_CAP_ASYNC_USB_LAB) != 0U);
  CHECK((manifest.safety_bits & ZS407_SAFETY_BINARY_TRANSPORT_LOCKED) != 0U);
  CHECK((manifest.safety_bits & ZS407_SAFETY_HARDWARE_CRC_UNQUALIFIED) != 0U);
  return 0;
}

int main(int argc, char **argv)
{
  if (argc != 2) {
    fprintf(stderr, "usage: %s fixture-directory\n", argv[0]);
    return 2;
  }
  CHECK(test_generated_payloads(argv[1]) == 0);
  CHECK(test_protocol_streaming() == 0);
  CHECK(test_trace_chunks() == 0);
  CHECK(test_compact_codecs() == 0);
  CHECK(test_spsc() == 0);
  CHECK(test_release_profile() == 0);
  puts("ZS407 protocol v2: all tests passed");
  return 0;
}
