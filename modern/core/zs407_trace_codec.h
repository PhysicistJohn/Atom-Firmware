/* SPDX-License-Identifier: GPL-3.0-or-later */
#ifndef ZS407_TRACE_CODEC_H
#define ZS407_TRACE_CODEC_H

#include "zs407_core.h"

typedef struct {
  zs407_trace_chunk_payload_t header;
  const uint8_t *sample_bytes;
  const uint8_t *validity_bitmap;
} zs407_trace_chunk_view_t;

enum {
  ZS407_TRACE_CHUNK_COMPLETE = UINT16_C(1) << 0,
  ZS407_TRACE_CHUNK_MONOTONIC_TIME = UINT16_C(1) << 1,
  ZS407_TRACE_CHUNK_DELTA_ENCODED = UINT16_C(1) << 2
};

size_t zs407_trace_chunk_payload_size(uint16_t point_count);
zs407_core_status_t zs407_trace_chunk_encode(
    const zs407_trace_chunk_payload_t *header,
    const zs407_db32_t *samples, uint8_t *output,
    size_t output_capacity, size_t *output_length);
zs407_core_status_t zs407_trace_chunk_decode(
    const uint8_t *payload, size_t payload_length,
    zs407_trace_chunk_view_t *view);
zs407_core_status_t zs407_trace_chunk_delta_encode(
    const zs407_trace_chunk_payload_t *header,
    const zs407_db32_t *samples, uint8_t *output,
    size_t output_capacity, size_t *output_length);
zs407_core_status_t zs407_trace_chunk_decode_samples(
    const uint8_t *payload, size_t payload_length,
    zs407_db32_t *samples, size_t sample_capacity,
    zs407_trace_chunk_payload_t *header);
bool zs407_trace_chunk_point_valid(const zs407_trace_chunk_view_t *view,
                                   uint16_t index);
zs407_db32_t zs407_trace_chunk_point(const zs407_trace_chunk_view_t *view,
                                     uint16_t index);

#endif /* ZS407_TRACE_CODEC_H */
