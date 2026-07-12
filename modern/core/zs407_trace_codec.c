/* SPDX-License-Identifier: GPL-3.0-or-later */
#include "zs407_trace_codec.h"
#include "zs407_compact.h"

#include <string.h>

static size_t validity_bytes(uint16_t point_count)
{
  return ((size_t)point_count + 7U) / 8U;
}

size_t zs407_trace_chunk_payload_size(uint16_t point_count)
{
  if (point_count == 0U ||
      point_count > ZS407_PROTOCOL_MAX_TRACE_CHUNK_POINTS) {
    return 0U;
  }
  return ZS407_TRACE_CHUNK_PAYLOAD_BYTES + (size_t)point_count * 2U +
         validity_bytes(point_count);
}

static bool valid_header(const zs407_trace_chunk_payload_t *header)
{
  return header != NULL && header->point_count != 0U &&
         header->point_count <= ZS407_PROTOCOL_MAX_TRACE_CHUNK_POINTS &&
         header->total_points != 0U &&
         header->total_points <= ZS407_PROTOCOL_MAX_TRACE_POINTS &&
         (uint32_t)header->start_index + header->point_count <=
             header->total_points &&
         header->frequency_step_denominator != 0U &&
         header->power_scale_db == ZS407_TRACE_DB_SCALE &&
         header->reserved == 0U;
}

zs407_core_status_t zs407_trace_chunk_encode(
    const zs407_trace_chunk_payload_t *header,
    const zs407_db32_t *samples, uint8_t *output,
    size_t output_capacity, size_t *output_length)
{
  if (!valid_header(header) ||
      (header->flags & ZS407_TRACE_CHUNK_DELTA_ENCODED) != 0U ||
      samples == NULL || output == NULL ||
      output_length == NULL) {
    return ZS407_CORE_INVALID_ARGUMENT;
  }
  size_t required = zs407_trace_chunk_payload_size(header->point_count);
  if (output_capacity < required) {
    return ZS407_CORE_BUFFER_TOO_SMALL;
  }
  zs407_trace_chunk_payload_t wire_header = *header;
  wire_header.validity_bytes = (uint16_t)validity_bytes(header->point_count);
  if (!zs407_trace_chunk_payload_encode(
          &wire_header, output, ZS407_TRACE_CHUNK_PAYLOAD_BYTES)) {
    return ZS407_CORE_INVALID_ARGUMENT;
  }

  uint8_t *sample_output = &output[ZS407_TRACE_CHUNK_PAYLOAD_BYTES];
  uint8_t *bitmap = &sample_output[(size_t)header->point_count * 2U];
  memset(bitmap, 0, wire_header.validity_bytes);
  for (uint16_t i = 0U; i < header->point_count; ++i) {
    zs407_contract_put_u16le(&sample_output[(size_t)i * 2U],
                             (uint16_t)samples[i]);
    if (samples[i] != ZS407_TRACE_INVALID_SAMPLE) {
      bitmap[i >> 3] |= (uint8_t)(1U << (i & 7U));
    }
  }
  *output_length = required;
  return ZS407_CORE_OK;
}

zs407_core_status_t zs407_trace_chunk_decode(
    const uint8_t *payload, size_t payload_length,
    zs407_trace_chunk_view_t *view)
{
  if (payload == NULL || view == NULL ||
      payload_length < ZS407_TRACE_CHUNK_PAYLOAD_BYTES ||
      !zs407_trace_chunk_payload_decode(
          payload, ZS407_TRACE_CHUNK_PAYLOAD_BYTES, &view->header) ||
      !valid_header(&view->header) ||
      (view->header.flags & ZS407_TRACE_CHUNK_DELTA_ENCODED) != 0U) {
    return ZS407_CORE_BAD_FRAME;
  }
  size_t bitmap_bytes = validity_bytes(view->header.point_count);
  size_t expected = zs407_trace_chunk_payload_size(view->header.point_count);
  if (view->header.validity_bytes != bitmap_bytes ||
      payload_length != expected) {
    return ZS407_CORE_BAD_FRAME;
  }
  view->sample_bytes = &payload[ZS407_TRACE_CHUNK_PAYLOAD_BYTES];
  view->validity_bitmap =
      &view->sample_bytes[(size_t)view->header.point_count * 2U];
  if ((view->header.point_count & 7U) != 0U) {
    uint8_t used_mask =
        (uint8_t)((1U << (view->header.point_count & 7U)) - 1U);
    if ((view->validity_bitmap[bitmap_bytes - 1U] &
         (uint8_t)~used_mask) != 0U) {
      return ZS407_CORE_BAD_FRAME;
    }
  }
  return ZS407_CORE_OK;
}

zs407_core_status_t zs407_trace_chunk_delta_encode(
    const zs407_trace_chunk_payload_t *header,
    const zs407_db32_t *samples, uint8_t *output,
    size_t output_capacity, size_t *output_length)
{
  if (!valid_header(header) || samples == NULL || output == NULL ||
      output_length == NULL ||
      output_capacity < ZS407_TRACE_CHUNK_PAYLOAD_BYTES) {
    return ZS407_CORE_INVALID_ARGUMENT;
  }
  zs407_trace_chunk_payload_t wire_header = *header;
  wire_header.flags |= ZS407_TRACE_CHUNK_DELTA_ENCODED;
  wire_header.validity_bytes = 0U;
  if (!zs407_trace_chunk_payload_encode(
          &wire_header, output, ZS407_TRACE_CHUNK_PAYLOAD_BYTES)) {
    return ZS407_CORE_INVALID_ARGUMENT;
  }
  size_t encoded_length = 0U;
  zs407_core_status_t status = zs407_trace_delta_encode(
      samples, header->point_count,
      &output[ZS407_TRACE_CHUNK_PAYLOAD_BYTES],
      output_capacity - ZS407_TRACE_CHUNK_PAYLOAD_BYTES, &encoded_length);
  if (status != ZS407_CORE_OK) {
    return status;
  }
  *output_length = ZS407_TRACE_CHUNK_PAYLOAD_BYTES + encoded_length;
  return ZS407_CORE_OK;
}

zs407_core_status_t zs407_trace_chunk_decode_samples(
    const uint8_t *payload, size_t payload_length,
    zs407_db32_t *samples, size_t sample_capacity,
    zs407_trace_chunk_payload_t *header)
{
  if (payload == NULL || samples == NULL || header == NULL ||
      payload_length < ZS407_TRACE_CHUNK_PAYLOAD_BYTES ||
      !zs407_trace_chunk_payload_decode(
          payload, ZS407_TRACE_CHUNK_PAYLOAD_BYTES, header) ||
      !valid_header(header) || sample_capacity < header->point_count) {
    return ZS407_CORE_BAD_FRAME;
  }
  if ((header->flags & ZS407_TRACE_CHUNK_DELTA_ENCODED) != 0U) {
    if (header->validity_bytes != 0U ||
        payload_length == ZS407_TRACE_CHUNK_PAYLOAD_BYTES) {
      return ZS407_CORE_BAD_FRAME;
    }
    return zs407_trace_delta_decode(
        &payload[ZS407_TRACE_CHUNK_PAYLOAD_BYTES],
        payload_length - ZS407_TRACE_CHUNK_PAYLOAD_BYTES,
        samples, header->point_count);
  }
  zs407_trace_chunk_view_t view;
  zs407_core_status_t status = zs407_trace_chunk_decode(
      payload, payload_length, &view);
  if (status != ZS407_CORE_OK) {
    return status;
  }
  for (uint16_t i = 0U; i < header->point_count; ++i) {
    samples[i] = zs407_trace_chunk_point(&view, i);
  }
  return ZS407_CORE_OK;
}

bool zs407_trace_chunk_point_valid(const zs407_trace_chunk_view_t *view,
                                   uint16_t index)
{
  return view != NULL && view->validity_bitmap != NULL &&
         index < view->header.point_count &&
         (view->validity_bitmap[index >> 3] &
          (uint8_t)(1U << (index & 7U))) != 0U;
}

zs407_db32_t zs407_trace_chunk_point(const zs407_trace_chunk_view_t *view,
                                     uint16_t index)
{
  if (view == NULL || view->sample_bytes == NULL ||
      index >= view->header.point_count) {
    return ZS407_TRACE_INVALID_SAMPLE;
  }
  return (zs407_db32_t)zs407_contract_get_u16le(
      &view->sample_bytes[(size_t)index * 2U]);
}
