/* SPDX-License-Identifier: GPL-3.0-or-later */
#include "zs407_compact.h"

#include <limits.h>

static uint64_t zigzag_encode(int64_t value)
{
  uint64_t bits = (uint64_t)value;
  uint64_t sign = 0U - (uint64_t)(value < 0);
  return (bits << 1) ^ sign;
}

static int64_t zigzag_decode(uint64_t value)
{
  uint64_t magnitude = value >> 1;
  return (value & 1U) == 0U ? (int64_t)magnitude
                            : -1 - (int64_t)magnitude;
}

zs407_core_status_t zs407_uleb128_encode(
    uint64_t value, uint8_t *output, size_t output_capacity,
    size_t *output_length)
{
  if (output == NULL || output_length == NULL) {
    return ZS407_CORE_INVALID_ARGUMENT;
  }
  size_t used = 0U;
  do {
    if (used >= output_capacity) {
      return ZS407_CORE_BUFFER_TOO_SMALL;
    }
    uint8_t byte = (uint8_t)(value & 0x7fU);
    value >>= 7;
    output[used++] = value == 0U ? byte : (uint8_t)(byte | 0x80U);
  } while (value != 0U);
  *output_length = used;
  return ZS407_CORE_OK;
}

zs407_core_status_t zs407_uleb128_decode(
    const uint8_t *input, size_t input_length, uint64_t *value,
    size_t *consumed)
{
  if (input == NULL || value == NULL || consumed == NULL) {
    return ZS407_CORE_INVALID_ARGUMENT;
  }
  uint64_t result = 0U;
  unsigned shift = 0U;
  for (size_t i = 0U; i < input_length && i < 10U; ++i) {
    uint8_t byte = input[i];
    uint64_t payload = byte & 0x7fU;
    if (shift == 63U && payload > 1U) {
      return ZS407_CORE_BAD_FRAME;
    }
    result |= payload << shift;
    if ((byte & 0x80U) == 0U) {
      *value = result;
      *consumed = i + 1U;
      return ZS407_CORE_OK;
    }
    shift += 7U;
  }
  return ZS407_CORE_BAD_FRAME;
}

static zs407_core_status_t append_varint(uint64_t value, uint8_t *output,
                                         size_t output_capacity,
                                         size_t *offset)
{
  size_t encoded = 0U;
  zs407_core_status_t status = zs407_uleb128_encode(
      value, &output[*offset], output_capacity - *offset, &encoded);
  if (status == ZS407_CORE_OK) {
    *offset += encoded;
  }
  return status;
}

static zs407_core_status_t read_varint(const uint8_t *input,
                                       size_t input_length, size_t *offset,
                                       uint64_t *value)
{
  size_t consumed = 0U;
  zs407_core_status_t status = zs407_uleb128_decode(
      &input[*offset], input_length - *offset, value, &consumed);
  if (status == ZS407_CORE_OK) {
    *offset += consumed;
  }
  return status;
}

zs407_core_status_t zs407_trace_delta_encode(
    const zs407_db32_t *samples, size_t sample_count,
    uint8_t *output, size_t output_capacity, size_t *output_length)
{
  if (samples == NULL || output == NULL || output_length == NULL ||
      sample_count == 0U || sample_count > ZS407_PROTOCOL_MAX_TRACE_POINTS) {
    return ZS407_CORE_INVALID_ARGUMENT;
  }
  size_t offset = 0U;
  int32_t previous = 0;
  for (size_t i = 0U; i < sample_count; ++i) {
    int32_t current = samples[i];
    int32_t delta = current - previous;
    zs407_core_status_t status = append_varint(
        zigzag_encode(delta), output, output_capacity, &offset);
    if (status != ZS407_CORE_OK) {
      return status;
    }
    previous = current;
  }
  *output_length = offset;
  return ZS407_CORE_OK;
}

zs407_core_status_t zs407_trace_delta_decode(
    const uint8_t *input, size_t input_length,
    zs407_db32_t *samples, size_t sample_count)
{
  if (input == NULL || samples == NULL || sample_count == 0U ||
      sample_count > ZS407_PROTOCOL_MAX_TRACE_POINTS) {
    return ZS407_CORE_INVALID_ARGUMENT;
  }
  size_t offset = 0U;
  int32_t previous = 0;
  for (size_t i = 0U; i < sample_count; ++i) {
    uint64_t encoded = 0U;
    zs407_core_status_t status = read_varint(
        input, input_length, &offset, &encoded);
    if (status != ZS407_CORE_OK) {
      return status;
    }
    int64_t delta = zigzag_decode(encoded);
    int64_t current = (int64_t)previous + delta;
    if (current < INT16_MIN || current > INT16_MAX) {
      return ZS407_CORE_BAD_FRAME;
    }
    samples[i] = (zs407_db32_t)current;
    previous = (int32_t)current;
  }
  return offset == input_length ? ZS407_CORE_OK : ZS407_CORE_BAD_FRAME;
}

zs407_core_status_t zs407_wave_events_compact_encode(
    const zs407_wave_event_t *events, size_t event_count,
    uint8_t *output, size_t output_capacity, size_t *output_length)
{
  if (events == NULL || output == NULL || output_length == NULL) {
    return ZS407_CORE_INVALID_ARGUMENT;
  }
  zs407_wave_program_report_t report;
  zs407_core_status_t status = zs407_validate_wave_program(
      events, event_count, &report);
  if (status != ZS407_CORE_OK) {
    return status;
  }
  size_t offset = 0U;
  uint32_t previous_time = 0U;
  for (size_t i = 0U; i < event_count; ++i) {
    status = append_varint(events[i].at_us - previous_time,
                           output, output_capacity, &offset);
    if (status != ZS407_CORE_OK) {
      return status;
    }
    if (offset >= output_capacity) {
      return ZS407_CORE_BUFFER_TOO_SMALL;
    }
    output[offset++] = events[i].opcode;
    status = append_varint(zigzag_encode(events[i].value),
                           output, output_capacity, &offset);
    if (status != ZS407_CORE_OK) {
      return status;
    }
    previous_time = events[i].at_us;
  }
  *output_length = offset;
  return ZS407_CORE_OK;
}

zs407_core_status_t zs407_wave_events_compact_decode(
    const uint8_t *input, size_t input_length,
    zs407_wave_event_t *events, size_t event_count)
{
  if (input == NULL || events == NULL || event_count < 2U ||
      event_count > UINT16_MAX) {
    return ZS407_CORE_INVALID_ARGUMENT;
  }
  size_t offset = 0U;
  uint32_t previous_time = 0U;
  for (size_t i = 0U; i < event_count; ++i) {
    uint64_t delta = 0U;
    uint64_t encoded_value = 0U;
    zs407_core_status_t status = read_varint(
        input, input_length, &offset, &delta);
    if (status != ZS407_CORE_OK || delta > UINT32_MAX - previous_time ||
        offset >= input_length) {
      return ZS407_CORE_BAD_FRAME;
    }
    uint8_t opcode = input[offset++];
    status = read_varint(input, input_length, &offset, &encoded_value);
    if (status != ZS407_CORE_OK || opcode > ZS407_EVENT_END) {
      return ZS407_CORE_BAD_FRAME;
    }
    events[i].at_us = previous_time + (uint32_t)delta;
    events[i].opcode = opcode;
    events[i].flags = 0U;
    events[i].reserved = 0U;
    events[i].value = zigzag_decode(encoded_value);
    previous_time = events[i].at_us;
  }
  if (offset != input_length) {
    return ZS407_CORE_BAD_FRAME;
  }
  zs407_wave_program_report_t report;
  return zs407_validate_wave_program(events, event_count, &report);
}
