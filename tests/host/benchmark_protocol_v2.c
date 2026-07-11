/* SPDX-License-Identifier: GPL-3.0-or-later */
#include "modern/core/zs407_compact.h"
#include "modern/core/zs407_protocol.h"

#include <inttypes.h>
#include <stdio.h>
#include <string.h>
#include <time.h>

#define CRC_ITERATIONS 200000U
#define PARSER_ITERATIONS 100000U

static uint64_t monotonic_ns(void)
{
  struct timespec now;
  if (clock_gettime(CLOCK_MONOTONIC, &now) != 0) {
    return 0U;
  }
  return (uint64_t)now.tv_sec * UINT64_C(1000000000) +
         (uint64_t)now.tv_nsec;
}

static uint32_t legacy_crc32(const uint8_t *data, size_t length)
{
  uint32_t crc = UINT32_C(0xffffffff);
  for (size_t i = 0U; i < length; ++i) {
    crc ^= data[i];
    for (unsigned bit = 0U; bit < 8U; ++bit) {
      uint32_t mask = 0U - (crc & 1U);
      crc = (crc >> 1) ^ (UINT32_C(0xedb88320) & mask);
    }
  }
  return ~crc;
}

static void consume(void *context, const zs407_frame_t *frame)
{
  uint32_t *checksum = (uint32_t *)context;
  *checksum += frame->request_id + frame->payload_length;
}

int main(void)
{
  uint8_t data[1024];
  for (size_t i = 0U; i < sizeof(data); ++i) {
    data[i] = (uint8_t)(i * 29U + i / 7U);
  }
  if (legacy_crc32(data, sizeof(data)) != zs407_crc32(data, sizeof(data))) {
    return 1;
  }

  volatile uint32_t checksum = 0U;
  uint64_t start = monotonic_ns();
  for (uint32_t i = 0U; i < CRC_ITERATIONS; ++i) {
    checksum ^= legacy_crc32(data, sizeof(data));
  }
  uint64_t legacy_ns = monotonic_ns() - start;
  start = monotonic_ns();
  for (uint32_t i = 0U; i < CRC_ITERATIONS; ++i) {
    checksum ^= zs407_crc32(data, sizeof(data));
  }
  uint64_t nibble_ns = monotonic_ns() - start;

  zs407_frame_t frame = {
      .version = 2U, .flags = 0U, .request_id = 407U,
      .command = ZS407_COMMAND_SWEEP_DATA, .payload = data,
      .payload_length = sizeof(data)};
  uint8_t encoded[ZS407_FRAME_MAX_BYTES];
  size_t encoded_length = 0U;
  if (zs407_frame_encode(&frame, encoded, sizeof(encoded), &encoded_length) !=
      ZS407_CORE_OK) {
    return 1;
  }
  uint8_t parser_storage[ZS407_FRAME_MAX_BYTES];
  zs407_stream_parser_t parser;
  if (zs407_stream_parser_init(&parser, parser_storage,
                               sizeof(parser_storage)) != ZS407_CORE_OK) {
    return 1;
  }
  uint32_t parser_checksum = 0U;
  start = monotonic_ns();
  for (uint32_t i = 0U; i < PARSER_ITERATIONS; ++i) {
    size_t accepted = 0U;
    if (zs407_stream_parser_feed(&parser, encoded, encoded_length,
                                  consume, &parser_checksum, &accepted) !=
            ZS407_CORE_OK ||
        accepted != 1U) {
      return 1;
    }
  }
  uint64_t parser_ns = monotonic_ns() - start;

  zs407_db32_t trace[450];
  uint8_t compact[1350];
  for (size_t i = 0U; i < 450U; ++i) {
    trace[i] = (zs407_db32_t)(-3000 + (int32_t)(i / 5U));
  }
  size_t compact_length = 0U;
  if (zs407_trace_delta_encode(trace, 450U, compact, sizeof(compact),
                               &compact_length) != ZS407_CORE_OK) {
    return 1;
  }

  double crc_speedup = nibble_ns == 0U ? 0.0 :
      (double)legacy_ns / (double)nibble_ns;
  double parser_mib_s = parser_ns == 0U ? 0.0 :
      ((double)encoded_length * PARSER_ITERATIONS * 1.0e9) /
      ((double)parser_ns * 1024.0 * 1024.0);
  printf("crc_legacy_ns=%" PRIu64 "\n", legacy_ns);
  printf("crc_nibble_ns=%" PRIu64 "\n", nibble_ns);
  printf("crc_speedup=%.3f\n", crc_speedup);
  printf("stream_parser_mib_s=%.3f\n", parser_mib_s);
  printf("trace_raw_bytes=%zu\n", sizeof(trace));
  printf("trace_delta_bytes=%zu\n", compact_length);
  printf("trace_ratio=%.3f\n", (double)compact_length / sizeof(trace));
  printf("checksum=%u\n", (uint32_t)checksum ^ parser_checksum);
  return 0;
}
