/* SPDX-License-Identifier: GPL-3.0-or-later */
#ifndef ZS407_TRACE_CODEC_H
#define ZS407_TRACE_CODEC_H

#include "zs407_core.h"

typedef struct {
  zs407_trace_chunk_payload_t header;
  const uint8_t *sample_bytes;
  const uint8_t *validity_bitmap;
} zs407_trace_chunk_view_t;

size_t zs407_trace_chunk_payload_size(uint16_t point_count);
zs407_core_status_t zs407_trace_chunk_encode(
    const zs407_trace_chunk_payload_t *header,
    const zs407_db32_t *samples, uint8_t *output,
    size_t output_capacity, size_t *output_length);
zs407_core_status_t zs407_trace_chunk_decode(
    const uint8_t *payload, size_t payload_length,
    zs407_trace_chunk_view_t *view);
bool zs407_trace_chunk_point_valid(const zs407_trace_chunk_view_t *view,
                                   uint16_t index);
zs407_db32_t zs407_trace_chunk_point(const zs407_trace_chunk_view_t *view,
                                     uint16_t index);

#endif /* ZS407_TRACE_CODEC_H */
