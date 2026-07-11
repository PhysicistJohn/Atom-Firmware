/* SPDX-License-Identifier: GPL-3.0-or-later */
#include "modern/core/zs407_compact.h"
#include "modern/core/zs407_protocol.h"
#include "modern/core/zs407_trace_codec.h"

#include <stddef.h>
#include <stdint.h>
#ifdef ZS407_STANDALONE_FUZZ
#include <stdio.h>
#endif

static void consume(void *context, const zs407_frame_t *frame)
{
  uint32_t *accumulator = (uint32_t *)context;
  *accumulator ^= frame->request_id;
  *accumulator += frame->payload_length;
}

int LLVMFuzzerTestOneInput(const uint8_t *data, size_t size)
{
  uint8_t parser_storage[ZS407_FRAME_MAX_BYTES];
  zs407_stream_parser_t parser;
  if (zs407_stream_parser_init(&parser, parser_storage,
                               sizeof(parser_storage)) != ZS407_CORE_OK) {
    return 0;
  }
  uint32_t accumulator = 0U;
  size_t offset = 0U;
  while (offset < size) {
    size_t count = (size_t)(data[offset] & 31U) + 1U;
    if (count > size - offset) {
      count = size - offset;
    }
    size_t accepted = 0U;
    (void)zs407_stream_parser_feed(&parser, &data[offset], count,
                                    consume, &accumulator, &accepted);
    accumulator += (uint32_t)accepted;
    offset += count;
  }

  if (size <= ZS407_FRAME_MAX_BYTES) {
    zs407_frame_t frame;
    if (zs407_frame_decode(data, size, &frame) == ZS407_CORE_OK) {
      accumulator ^= zs407_crc32(frame.payload, frame.payload_length);
    }
  }
  zs407_trace_chunk_view_t view;
  if (zs407_trace_chunk_decode(data, size, &view) == ZS407_CORE_OK &&
      view.header.point_count != 0U) {
    accumulator ^= (uint16_t)zs407_trace_chunk_point(&view, 0U);
  }
  uint64_t varint = 0U;
  size_t consumed = 0U;
  if (size != 0U &&
      zs407_uleb128_decode(data, size, &varint, &consumed) ==
          ZS407_CORE_OK) {
    accumulator ^= (uint32_t)varint ^ (uint32_t)consumed;
  }
  if (size != 0U) {
    zs407_db32_t samples[64];
    size_t sample_count = (size_t)(data[0] & 63U) + 1U;
    (void)zs407_trace_delta_decode(data, size, samples, sample_count);
  }
  return accumulator == UINT32_C(0x40740740) ? 1 : 0;
}

#ifdef ZS407_STANDALONE_FUZZ
static uint32_t random_state = UINT32_C(0x407f0220);

static uint32_t next_random(void)
{
  random_state ^= random_state << 13;
  random_state ^= random_state >> 17;
  random_state ^= random_state << 5;
  return random_state;
}

int main(void)
{
  uint8_t input[2048];
  uint8_t payload[1024];
  for (uint32_t iteration = 0U; iteration < 100000U; ++iteration) {
    size_t length = next_random() % sizeof(input);
    for (size_t i = 0U; i < length; ++i) {
      input[i] = (uint8_t)next_random();
    }
    if ((iteration & 1U) != 0U) {
      uint16_t payload_length = (uint16_t)(next_random() % sizeof(payload));
      for (uint16_t i = 0U; i < payload_length; ++i) {
        payload[i] = (uint8_t)next_random();
      }
      zs407_frame_t frame = {
          .version = (uint8_t)(1U + (next_random() & 1U)),
          .flags = (uint8_t)next_random(),
          .request_id = (uint16_t)next_random(),
          .command = (uint16_t)next_random(),
          .payload = payload,
          .payload_length = payload_length};
      if (zs407_frame_encode(&frame, input, sizeof(input), &length) !=
          ZS407_CORE_OK) {
        return 2;
      }
      if ((iteration % 5U) == 0U && length != 0U) {
        input[next_random() % length] ^= (uint8_t)(1U << (next_random() & 7U));
      }
    }
    (void)LLVMFuzzerTestOneInput(input, length);
  }
  puts("ZS407 protocol mutation fuzz: 100000 cases passed");
  return 0;
}
#endif
