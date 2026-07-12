/* SPDX-License-Identifier: GPL-3.0-or-later */
#ifndef ZS407_PROTOCOL_H
#define ZS407_PROTOCOL_H

#include "zs407_core.h"

#define ZS407_FRAME_HEADER_BYTES 10U
#define ZS407_FRAME_TRAILER_BYTES 4U
#define ZS407_FRAME_OVERHEAD_BYTES \
  (ZS407_FRAME_HEADER_BYTES + ZS407_FRAME_TRAILER_BYTES)
#define ZS407_FRAME_MAX_BYTES \
  (ZS407_FRAME_OVERHEAD_BYTES + ZS407_PROTOCOL_MAX_PAYLOAD)

typedef struct {
  uint32_t state;
} zs407_crc32_context_t;

void zs407_crc32_init(zs407_crc32_context_t *context);
void zs407_crc32_update(zs407_crc32_context_t *context,
                        const uint8_t *data, size_t length);
uint32_t zs407_crc32_final(const zs407_crc32_context_t *context);
uint32_t zs407_crc32(const uint8_t *data, size_t length);

typedef struct {
  uint8_t version;
  uint8_t flags;
  uint16_t request_id;
  uint16_t command;
  const uint8_t *payload;
  uint16_t payload_length;
} zs407_frame_t;

typedef struct {
  const uint8_t *data;
  uint16_t length;
} zs407_bytes_t;

typedef zs407_core_status_t (*zs407_byte_sink_t)(
    void *context, const uint8_t *data, size_t length);

zs407_core_status_t zs407_frame_encode(const zs407_frame_t *frame,
                                       uint8_t *output,
                                       size_t output_capacity,
                                       size_t *output_length);
zs407_core_status_t zs407_frame_begin(const zs407_frame_t *frame,
                                      uint8_t *output,
                                      size_t output_capacity,
                                      uint8_t **payload_output);
zs407_core_status_t zs407_frame_finish(uint8_t *output,
                                       size_t output_capacity,
                                       size_t *output_length);
zs407_core_status_t zs407_frame_resize_payload(uint8_t *output,
                                               size_t output_capacity,
                                               uint16_t payload_length);
zs407_core_status_t zs407_frame_encode_segments(
    const zs407_frame_t *metadata, const zs407_bytes_t *segments,
    size_t segment_count, uint8_t *output, size_t output_capacity,
    size_t *output_length);
zs407_core_status_t zs407_frame_write_segments(
    const zs407_frame_t *metadata, const zs407_bytes_t *segments,
    size_t segment_count, zs407_byte_sink_t sink, void *sink_context,
    size_t *output_length);
zs407_core_status_t zs407_frame_decode(const uint8_t *input,
                                       size_t input_length,
                                       zs407_frame_t *frame);

typedef void (*zs407_frame_consumer_t)(void *context,
                                       const zs407_frame_t *frame);

typedef struct {
  uint8_t *storage;
  size_t storage_capacity;
  size_t used;
  size_t expected;
  size_t crc_bytes;
  zs407_crc32_context_t crc;
  uint32_t accepted_frames;
  uint32_t rejected_frames;
  uint32_t discarded_bytes;
} zs407_stream_parser_t;

zs407_core_status_t zs407_stream_parser_init(
    zs407_stream_parser_t *parser, uint8_t *storage,
    size_t storage_capacity);
void zs407_stream_parser_reset(zs407_stream_parser_t *parser);
zs407_core_status_t zs407_stream_parser_feed(
    zs407_stream_parser_t *parser, const uint8_t *input,
    size_t input_length, zs407_frame_consumer_t consumer,
    void *consumer_context, size_t *accepted_frames);

#endif /* ZS407_PROTOCOL_H */
