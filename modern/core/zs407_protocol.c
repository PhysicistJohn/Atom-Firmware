/* SPDX-License-Identifier: GPL-3.0-or-later */
#include "zs407_protocol.h"

#include <string.h>

/* 64 bytes instead of a 1 KiB byte lookup table. */
static const uint32_t crc32_nibble[16] = {
    UINT32_C(0x00000000), UINT32_C(0x1db71064),
    UINT32_C(0x3b6e20c8), UINT32_C(0x26d930ac),
    UINT32_C(0x76dc4190), UINT32_C(0x6b6b51f4),
    UINT32_C(0x4db26158), UINT32_C(0x5005713c),
    UINT32_C(0xedb88320), UINT32_C(0xf00f9344),
    UINT32_C(0xd6d6a3e8), UINT32_C(0xcb61b38c),
    UINT32_C(0x9b64c2b0), UINT32_C(0x86d3d2d4),
    UINT32_C(0xa00ae278), UINT32_C(0xbdbdf21c)};

static bool version_supported(uint8_t version)
{
  return version >= ZS407_PROTOCOL_MINIMUM_VERSION &&
         version <= ZS407_PROTOCOL_VERSION;
}

static uint8_t frame_version(const zs407_frame_t *frame)
{
  return frame->version == 0U ? (uint8_t)ZS407_PROTOCOL_VERSION
                              : frame->version;
}

void zs407_crc32_init(zs407_crc32_context_t *context)
{
  if (context != NULL) {
    context->state = UINT32_C(0xffffffff);
  }
}

void zs407_crc32_update(zs407_crc32_context_t *context,
                        const uint8_t *data, size_t length)
{
  if (context == NULL || (data == NULL && length != 0U)) {
    return;
  }
  uint32_t crc = context->state;
  for (size_t i = 0U; i < length; ++i) {
    crc ^= data[i];
    crc = (crc >> 4) ^ crc32_nibble[crc & 0x0fU];
    crc = (crc >> 4) ^ crc32_nibble[crc & 0x0fU];
  }
  context->state = crc;
}

uint32_t zs407_crc32_final(const zs407_crc32_context_t *context)
{
  return context == NULL ? 0U : ~context->state;
}

uint32_t zs407_crc32(const uint8_t *data, size_t length)
{
  if (data == NULL && length != 0U) {
    return 0U;
  }
  zs407_crc32_context_t context;
  zs407_crc32_init(&context);
  zs407_crc32_update(&context, data, length);
  return zs407_crc32_final(&context);
}

static zs407_core_status_t validate_frame(const zs407_frame_t *frame)
{
  if (frame == NULL) {
    return ZS407_CORE_INVALID_ARGUMENT;
  }
  if (!version_supported(frame_version(frame))) {
    return ZS407_CORE_UNSUPPORTED;
  }
  if (frame->payload_length > ZS407_PROTOCOL_MAX_PAYLOAD) {
    return ZS407_CORE_OUT_OF_RANGE;
  }
  return ZS407_CORE_OK;
}

static void write_header(const zs407_frame_t *frame, uint16_t payload_length,
                         uint8_t output[ZS407_FRAME_HEADER_BYTES])
{
  zs407_contract_put_u16le(&output[0], (uint16_t)ZS407_PROTOCOL_MAGIC);
  output[2] = frame_version(frame);
  output[3] = frame->flags;
  zs407_contract_put_u16le(&output[4], frame->request_id);
  zs407_contract_put_u16le(&output[6], frame->command);
  zs407_contract_put_u16le(&output[8], payload_length);
}

zs407_core_status_t zs407_frame_begin(const zs407_frame_t *frame,
                                      uint8_t *output,
                                      size_t output_capacity,
                                      uint8_t **payload_output)
{
  if (output == NULL || payload_output == NULL) {
    return ZS407_CORE_INVALID_ARGUMENT;
  }
  zs407_core_status_t status = validate_frame(frame);
  if (status != ZS407_CORE_OK) {
    return status;
  }
  size_t total = ZS407_FRAME_OVERHEAD_BYTES + frame->payload_length;
  if (output_capacity < total) {
    return ZS407_CORE_BUFFER_TOO_SMALL;
  }
  write_header(frame, frame->payload_length, output);
  *payload_output = &output[ZS407_FRAME_HEADER_BYTES];
  return ZS407_CORE_OK;
}

zs407_core_status_t zs407_frame_finish(uint8_t *output,
                                       size_t output_capacity,
                                       size_t *output_length)
{
  if (output == NULL || output_length == NULL ||
      output_capacity < ZS407_FRAME_OVERHEAD_BYTES ||
      zs407_contract_get_u16le(output) != ZS407_PROTOCOL_MAGIC ||
      !version_supported(output[2])) {
    return ZS407_CORE_INVALID_ARGUMENT;
  }
  uint16_t payload_length = zs407_contract_get_u16le(&output[8]);
  if (payload_length > ZS407_PROTOCOL_MAX_PAYLOAD) {
    return ZS407_CORE_OUT_OF_RANGE;
  }
  size_t crc_length = ZS407_FRAME_HEADER_BYTES + payload_length;
  size_t total = crc_length + ZS407_FRAME_TRAILER_BYTES;
  if (output_capacity < total) {
    return ZS407_CORE_BUFFER_TOO_SMALL;
  }
  zs407_contract_put_u32le(&output[crc_length],
                           zs407_crc32(output, crc_length));
  *output_length = total;
  return ZS407_CORE_OK;
}

zs407_core_status_t zs407_frame_resize_payload(uint8_t *output,
                                               size_t output_capacity,
                                               uint16_t payload_length)
{
  if (output == NULL || output_capacity < ZS407_FRAME_OVERHEAD_BYTES ||
      zs407_contract_get_u16le(output) != ZS407_PROTOCOL_MAGIC ||
      !version_supported(output[2])) {
    return ZS407_CORE_INVALID_ARGUMENT;
  }
  if (payload_length > ZS407_PROTOCOL_MAX_PAYLOAD) {
    return ZS407_CORE_OUT_OF_RANGE;
  }
  if (output_capacity < ZS407_FRAME_OVERHEAD_BYTES + payload_length) {
    return ZS407_CORE_BUFFER_TOO_SMALL;
  }
  zs407_contract_put_u16le(&output[8], payload_length);
  return ZS407_CORE_OK;
}

zs407_core_status_t zs407_frame_encode(const zs407_frame_t *frame,
                                       uint8_t *output,
                                       size_t output_capacity,
                                       size_t *output_length)
{
  if (output_length == NULL || frame == NULL ||
      (frame->payload == NULL && frame->payload_length != 0U)) {
    return ZS407_CORE_INVALID_ARGUMENT;
  }
  uint8_t *payload_output = NULL;
  zs407_core_status_t status = zs407_frame_begin(
      frame, output, output_capacity, &payload_output);
  if (status != ZS407_CORE_OK) {
    return status;
  }
  if (frame->payload_length != 0U) {
    memcpy(payload_output, frame->payload, frame->payload_length);
  }
  return zs407_frame_finish(output, output_capacity, output_length);
}

static zs407_core_status_t segments_length(const zs407_bytes_t *segments,
                                            size_t segment_count,
                                            uint16_t *payload_length)
{
  if ((segments == NULL && segment_count != 0U) || payload_length == NULL) {
    return ZS407_CORE_INVALID_ARGUMENT;
  }
  size_t total = 0U;
  for (size_t i = 0U; i < segment_count; ++i) {
    if (segments[i].data == NULL && segments[i].length != 0U) {
      return ZS407_CORE_INVALID_ARGUMENT;
    }
    total += segments[i].length;
    if (total > ZS407_PROTOCOL_MAX_PAYLOAD) {
      return ZS407_CORE_OUT_OF_RANGE;
    }
  }
  *payload_length = (uint16_t)total;
  return ZS407_CORE_OK;
}

zs407_core_status_t zs407_frame_encode_segments(
    const zs407_frame_t *metadata, const zs407_bytes_t *segments,
    size_t segment_count, uint8_t *output, size_t output_capacity,
    size_t *output_length)
{
  if (metadata == NULL || output == NULL || output_length == NULL) {
    return ZS407_CORE_INVALID_ARGUMENT;
  }
  uint16_t payload_length = 0U;
  zs407_core_status_t status = segments_length(
      segments, segment_count, &payload_length);
  if (status != ZS407_CORE_OK) {
    return status;
  }
  zs407_frame_t frame = *metadata;
  frame.payload = payload_length == 0U ? NULL : (const uint8_t *)segments;
  frame.payload_length = payload_length;
  uint8_t *payload_output = NULL;
  status = zs407_frame_begin(&frame, output, output_capacity, &payload_output);
  if (status != ZS407_CORE_OK) {
    return status;
  }
  for (size_t i = 0U; i < segment_count; ++i) {
    if (segments[i].length != 0U) {
      memcpy(payload_output, segments[i].data, segments[i].length);
      payload_output += segments[i].length;
    }
  }
  return zs407_frame_finish(output, output_capacity, output_length);
}

zs407_core_status_t zs407_frame_write_segments(
    const zs407_frame_t *metadata, const zs407_bytes_t *segments,
    size_t segment_count, zs407_byte_sink_t sink, void *sink_context,
    size_t *output_length)
{
  if (metadata == NULL || sink == NULL || output_length == NULL) {
    return ZS407_CORE_INVALID_ARGUMENT;
  }
  uint16_t payload_length = 0U;
  zs407_core_status_t status = segments_length(
      segments, segment_count, &payload_length);
  if (status != ZS407_CORE_OK) {
    return status;
  }
  zs407_frame_t frame = *metadata;
  frame.payload = payload_length == 0U ? NULL : (const uint8_t *)segments;
  frame.payload_length = payload_length;
  status = validate_frame(&frame);
  if (status != ZS407_CORE_OK) {
    return status;
  }

  uint8_t header[ZS407_FRAME_HEADER_BYTES];
  uint8_t trailer[ZS407_FRAME_TRAILER_BYTES];
  write_header(&frame, payload_length, header);
  zs407_crc32_context_t crc;
  zs407_crc32_init(&crc);
  zs407_crc32_update(&crc, header, sizeof(header));
  status = sink(sink_context, header, sizeof(header));
  if (status != ZS407_CORE_OK) {
    return status;
  }
  for (size_t i = 0U; i < segment_count; ++i) {
    zs407_crc32_update(&crc, segments[i].data, segments[i].length);
    if (segments[i].length != 0U) {
      status = sink(sink_context, segments[i].data, segments[i].length);
      if (status != ZS407_CORE_OK) {
        return status;
      }
    }
  }
  zs407_contract_put_u32le(trailer, zs407_crc32_final(&crc));
  status = sink(sink_context, trailer, sizeof(trailer));
  if (status == ZS407_CORE_OK) {
    *output_length = ZS407_FRAME_OVERHEAD_BYTES + payload_length;
  }
  return status;
}

zs407_core_status_t zs407_frame_decode(const uint8_t *input,
                                       size_t input_length,
                                       zs407_frame_t *frame)
{
  if (input == NULL || frame == NULL) {
    return ZS407_CORE_INVALID_ARGUMENT;
  }
  if (input_length < ZS407_FRAME_OVERHEAD_BYTES ||
      zs407_contract_get_u16le(input) != ZS407_PROTOCOL_MAGIC ||
      !version_supported(input[2])) {
    return ZS407_CORE_BAD_FRAME;
  }
  uint16_t payload_length = zs407_contract_get_u16le(&input[8]);
  if (payload_length > ZS407_PROTOCOL_MAX_PAYLOAD ||
      input_length != ZS407_FRAME_OVERHEAD_BYTES + payload_length) {
    return ZS407_CORE_BAD_FRAME;
  }
  size_t crc_length = ZS407_FRAME_HEADER_BYTES + payload_length;
  uint32_t expected = zs407_contract_get_u32le(&input[crc_length]);
  if (expected != zs407_crc32(input, crc_length)) {
    return ZS407_CORE_BAD_FRAME;
  }

  frame->version = input[2];
  frame->flags = input[3];
  frame->request_id = zs407_contract_get_u16le(&input[4]);
  frame->command = zs407_contract_get_u16le(&input[6]);
  frame->payload_length = payload_length;
  frame->payload = &input[ZS407_FRAME_HEADER_BYTES];
  return ZS407_CORE_OK;
}

zs407_core_status_t zs407_stream_parser_init(
    zs407_stream_parser_t *parser, uint8_t *storage,
    size_t storage_capacity)
{
  if (parser == NULL || storage == NULL ||
      storage_capacity < ZS407_FRAME_OVERHEAD_BYTES) {
    return ZS407_CORE_INVALID_ARGUMENT;
  }
  memset(parser, 0, sizeof(*parser));
  parser->storage = storage;
  parser->storage_capacity = storage_capacity;
  zs407_crc32_init(&parser->crc);
  return ZS407_CORE_OK;
}

void zs407_stream_parser_reset(zs407_stream_parser_t *parser)
{
  if (parser != NULL) {
    parser->used = 0U;
    parser->expected = 0U;
    parser->crc_bytes = 0U;
    zs407_crc32_init(&parser->crc);
  }
}

static void parser_discard(zs407_stream_parser_t *parser)
{
  parser->discarded_bytes += (uint32_t)parser->used;
  zs407_stream_parser_reset(parser);
}

static void parser_resynchronize(zs407_stream_parser_t *parser)
{
  const uint8_t magic_low = (uint8_t)ZS407_PROTOCOL_MAGIC;
  const uint8_t magic_high = (uint8_t)(ZS407_PROTOCOL_MAGIC >> 8);
  size_t previous_used = parser->used;
  for (size_t i = 1U; i < previous_used; ++i) {
    if (parser->storage[i] != magic_low) {
      continue;
    }
    if (i + 1U == previous_used) {
      parser->storage[0] = magic_low;
      parser->discarded_bytes += (uint32_t)(previous_used - 1U);
      parser->used = 1U;
      parser->expected = 0U;
      parser->crc_bytes = 0U;
      zs407_crc32_init(&parser->crc);
      return;
    }
    if (parser->storage[i + 1U] != magic_high ||
        (i + 2U < previous_used &&
         !version_supported(parser->storage[i + 2U]))) {
      continue;
    }
    size_t retained = previous_used - i;
    memmove(parser->storage, &parser->storage[i], retained);
    parser->discarded_bytes += (uint32_t)i;
    parser->used = retained;
    parser->expected = 0U;
    parser->crc_bytes = 0U;
    zs407_crc32_init(&parser->crc);
    return;
  }
  parser_discard(parser);
}

static bool parser_header(zs407_stream_parser_t *parser)
{
  if (zs407_contract_get_u16le(parser->storage) != ZS407_PROTOCOL_MAGIC ||
      !version_supported(parser->storage[2])) {
    return false;
  }
  uint16_t payload_length = zs407_contract_get_u16le(&parser->storage[8]);
  size_t expected = ZS407_FRAME_OVERHEAD_BYTES + payload_length;
  if (payload_length > ZS407_PROTOCOL_MAX_PAYLOAD ||
      expected > parser->storage_capacity) {
    return false;
  }
  parser->expected = expected;
  parser->crc_bytes = 0U;
  zs407_crc32_init(&parser->crc);
  return true;
}

static void parser_crc_catch_up(zs407_stream_parser_t *parser)
{
  size_t payload_end = parser->expected - ZS407_FRAME_TRAILER_BYTES;
  size_t target = parser->used < payload_end ? parser->used : payload_end;
  if (target > parser->crc_bytes) {
    zs407_crc32_update(&parser->crc, &parser->storage[parser->crc_bytes],
                       target - parser->crc_bytes);
    parser->crc_bytes = target;
  }
}

static void parser_complete(zs407_stream_parser_t *parser,
                            zs407_frame_consumer_t consumer,
                            void *consumer_context,
                            size_t *accepted)
{
  size_t crc_length = parser->expected - ZS407_FRAME_TRAILER_BYTES;
  uint32_t expected_crc =
      zs407_contract_get_u32le(&parser->storage[crc_length]);
  if (expected_crc == zs407_crc32_final(&parser->crc)) {
    zs407_frame_t frame = {
        .version = parser->storage[2],
        .flags = parser->storage[3],
        .request_id = zs407_contract_get_u16le(&parser->storage[4]),
        .command = zs407_contract_get_u16le(&parser->storage[6]),
        .payload = &parser->storage[ZS407_FRAME_HEADER_BYTES],
        .payload_length = zs407_contract_get_u16le(&parser->storage[8])};
    parser->accepted_frames++;
    (*accepted)++;
    if (consumer != NULL) {
      consumer(consumer_context, &frame);
    }
  } else {
    parser->rejected_frames++;
  }
  zs407_stream_parser_reset(parser);
}

zs407_core_status_t zs407_stream_parser_feed(
    zs407_stream_parser_t *parser, const uint8_t *input,
    size_t input_length, zs407_frame_consumer_t consumer,
    void *consumer_context, size_t *accepted_frames)
{
  if (parser == NULL || parser->storage == NULL || accepted_frames == NULL ||
      (input == NULL && input_length != 0U)) {
    return ZS407_CORE_INVALID_ARGUMENT;
  }
  *accepted_frames = 0U;
  const uint8_t magic_low = (uint8_t)ZS407_PROTOCOL_MAGIC;
  const uint8_t magic_high = (uint8_t)(ZS407_PROTOCOL_MAGIC >> 8);
  size_t input_offset = 0U;

  while (input_offset < input_length) {
    if (parser->used == 0U) {
      const uint8_t *found = (const uint8_t *)memchr(
          &input[input_offset], magic_low, input_length - input_offset);
      if (found == NULL) {
        parser->discarded_bytes += (uint32_t)(input_length - input_offset);
        break;
      }
      parser->discarded_bytes +=
          (uint32_t)((size_t)(found - &input[input_offset]));
      parser->storage[0] = *found;
      parser->used = 1U;
      input_offset = (size_t)(found - input) + 1U;
      continue;
    }
    if (parser->used == 1U) {
      uint8_t byte = input[input_offset++];
      if (byte == magic_high) {
        parser->storage[1] = byte;
        parser->used = 2U;
      } else if (byte != magic_low) {
        parser->discarded_bytes += 2U;
        parser->used = 0U;
      } else {
        parser->discarded_bytes++;
      }
      continue;
    }
    if (parser->used < ZS407_FRAME_HEADER_BYTES) {
      size_t count = ZS407_FRAME_HEADER_BYTES - parser->used;
      size_t available = input_length - input_offset;
      if (count > available) {
        count = available;
      }
      memcpy(&parser->storage[parser->used], &input[input_offset], count);
      parser->used += count;
      input_offset += count;
      if (parser->used < ZS407_FRAME_HEADER_BYTES) {
        continue;
      }
      if (!parser_header(parser)) {
        parser->rejected_frames++;
        parser_resynchronize(parser);
        continue;
      }
      parser_crc_catch_up(parser);
    }

    if (parser->used >= ZS407_FRAME_HEADER_BYTES &&
        parser->expected == 0U) {
      if (!parser_header(parser)) {
        parser->rejected_frames++;
        parser_resynchronize(parser);
        continue;
      }
      parser_crc_catch_up(parser);
    }

    size_t remaining = parser->expected - parser->used;
    size_t available = input_length - input_offset;
    size_t count = remaining < available ? remaining : available;
    memcpy(&parser->storage[parser->used], &input[input_offset], count);
    parser->used += count;
    input_offset += count;
    parser_crc_catch_up(parser);
    if (parser->used == parser->expected) {
      parser_complete(parser, consumer, consumer_context, accepted_frames);
    }
  }
  return ZS407_CORE_OK;
}
