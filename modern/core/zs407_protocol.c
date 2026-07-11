/* SPDX-License-Identifier: GPL-3.0-or-later */
#include "zs407_protocol.h"

static void put_u16le(uint8_t *output, uint16_t value)
{
  output[0] = (uint8_t)value;
  output[1] = (uint8_t)(value >> 8);
}

static void put_u32le(uint8_t *output, uint32_t value)
{
  output[0] = (uint8_t)value;
  output[1] = (uint8_t)(value >> 8);
  output[2] = (uint8_t)(value >> 16);
  output[3] = (uint8_t)(value >> 24);
}

static uint16_t get_u16le(const uint8_t *input)
{
  return (uint16_t)((uint16_t)input[0] | ((uint16_t)input[1] << 8));
}

static uint32_t get_u32le(const uint8_t *input)
{
  return (uint32_t)input[0] | ((uint32_t)input[1] << 8) |
         ((uint32_t)input[2] << 16) | ((uint32_t)input[3] << 24);
}

uint32_t zs407_crc32(const uint8_t *data, size_t length)
{
  uint32_t crc = UINT32_C(0xffffffff);
  if (data == NULL && length != 0U) {
    return 0U;
  }
  for (size_t i = 0U; i < length; ++i) {
    crc ^= data[i];
    for (unsigned bit = 0U; bit < 8U; ++bit) {
      uint32_t mask = 0U - (crc & 1U);
      crc = (crc >> 1) ^ (UINT32_C(0xedb88320) & mask);
    }
  }
  return ~crc;
}

zs407_core_status_t zs407_frame_encode(const zs407_frame_t *frame,
                                       uint8_t *output,
                                       size_t output_capacity,
                                       size_t *output_length)
{
  if (frame == NULL || output == NULL || output_length == NULL ||
      (frame->payload == NULL && frame->payload_length != 0U)) {
    return ZS407_CORE_INVALID_ARGUMENT;
  }
  if (frame->payload_length > ZS407_PROTOCOL_MAX_PAYLOAD) {
    return ZS407_CORE_OUT_OF_RANGE;
  }
  size_t total = ZS407_FRAME_OVERHEAD_BYTES + frame->payload_length;
  if (output_capacity < total) {
    return ZS407_CORE_BUFFER_TOO_SMALL;
  }

  put_u16le(&output[0], (uint16_t)ZS407_PROTOCOL_MAGIC);
  output[2] = (uint8_t)ZS407_PROTOCOL_VERSION;
  output[3] = frame->flags;
  put_u16le(&output[4], frame->request_id);
  put_u16le(&output[6], frame->command);
  put_u16le(&output[8], frame->payload_length);
  for (size_t i = 0U; i < frame->payload_length; ++i) {
    output[ZS407_FRAME_HEADER_BYTES + i] = frame->payload[i];
  }
  put_u32le(&output[ZS407_FRAME_HEADER_BYTES + frame->payload_length],
            zs407_crc32(output,
                        ZS407_FRAME_HEADER_BYTES + frame->payload_length));
  *output_length = total;
  return ZS407_CORE_OK;
}

zs407_core_status_t zs407_frame_decode(const uint8_t *input,
                                       size_t input_length,
                                       zs407_frame_t *frame)
{
  if (input == NULL || frame == NULL) {
    return ZS407_CORE_INVALID_ARGUMENT;
  }
  if (input_length < ZS407_FRAME_OVERHEAD_BYTES ||
      get_u16le(&input[0]) != ZS407_PROTOCOL_MAGIC ||
      input[2] != ZS407_PROTOCOL_VERSION) {
    return ZS407_CORE_BAD_FRAME;
  }
  uint16_t payload_length = get_u16le(&input[8]);
  if (payload_length > ZS407_PROTOCOL_MAX_PAYLOAD ||
      input_length != ZS407_FRAME_OVERHEAD_BYTES + payload_length) {
    return ZS407_CORE_BAD_FRAME;
  }
  uint32_t expected = get_u32le(&input[ZS407_FRAME_HEADER_BYTES +
                                         payload_length]);
  uint32_t actual = zs407_crc32(input,
                                ZS407_FRAME_HEADER_BYTES + payload_length);
  if (expected != actual) {
    return ZS407_CORE_BAD_FRAME;
  }

  frame->flags = input[3];
  frame->request_id = get_u16le(&input[4]);
  frame->command = get_u16le(&input[6]);
  frame->payload_length = payload_length;
  frame->payload = &input[ZS407_FRAME_HEADER_BYTES];
  return ZS407_CORE_OK;
}
