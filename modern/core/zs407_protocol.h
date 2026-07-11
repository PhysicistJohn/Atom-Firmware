/* SPDX-License-Identifier: GPL-3.0-or-later */
#ifndef ZS407_PROTOCOL_H
#define ZS407_PROTOCOL_H

#include "zs407_core.h"

#define ZS407_FRAME_HEADER_BYTES 10U
#define ZS407_FRAME_TRAILER_BYTES 4U
#define ZS407_FRAME_OVERHEAD_BYTES \
  (ZS407_FRAME_HEADER_BYTES + ZS407_FRAME_TRAILER_BYTES)

typedef struct {
  uint8_t flags;
  uint16_t request_id;
  uint16_t command;
  const uint8_t *payload;
  uint16_t payload_length;
} zs407_frame_t;

uint32_t zs407_crc32(const uint8_t *data, size_t length);
zs407_core_status_t zs407_frame_encode(const zs407_frame_t *frame,
                                       uint8_t *output,
                                       size_t output_capacity,
                                       size_t *output_length);
zs407_core_status_t zs407_frame_decode(const uint8_t *input,
                                       size_t input_length,
                                       zs407_frame_t *frame);

#endif /* ZS407_PROTOCOL_H */
