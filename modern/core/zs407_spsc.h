/* SPDX-License-Identifier: GPL-3.0-or-later */
#ifndef ZS407_SPSC_H
#define ZS407_SPSC_H

#include "zs407_core.h"

typedef struct {
  uint8_t *data;
  uint32_t capacity;
  uint32_t mask;
  uint32_t head;
  uint32_t tail;
} zs407_spsc_ring_t;

zs407_core_status_t zs407_spsc_ring_init(zs407_spsc_ring_t *ring,
                                         uint8_t *storage,
                                         size_t storage_capacity);
size_t zs407_spsc_ring_available(const zs407_spsc_ring_t *ring);
size_t zs407_spsc_ring_free(const zs407_spsc_ring_t *ring);
size_t zs407_spsc_ring_write(zs407_spsc_ring_t *ring,
                             const uint8_t *input, size_t input_length);
size_t zs407_spsc_ring_read(zs407_spsc_ring_t *ring,
                            uint8_t *output, size_t output_capacity);

#endif /* ZS407_SPSC_H */
