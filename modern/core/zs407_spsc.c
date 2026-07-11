/* SPDX-License-Identifier: GPL-3.0-or-later */
#include "zs407_spsc.h"

#include <string.h>

static uint32_t load_acquire(const uint32_t *value)
{
  return __atomic_load_n(value, __ATOMIC_ACQUIRE);
}

static uint32_t load_relaxed(const uint32_t *value)
{
  return __atomic_load_n(value, __ATOMIC_RELAXED);
}

static void store_release(uint32_t *target, uint32_t value)
{
  __atomic_store_n(target, value, __ATOMIC_RELEASE);
}

zs407_core_status_t zs407_spsc_ring_init(zs407_spsc_ring_t *ring,
                                         uint8_t *storage,
                                         size_t storage_capacity)
{
  if (ring == NULL || storage == NULL || storage_capacity < 2U ||
      storage_capacity > UINT32_MAX / 2U ||
      (storage_capacity & (storage_capacity - 1U)) != 0U) {
    return ZS407_CORE_INVALID_ARGUMENT;
  }
  ring->data = storage;
  ring->capacity = (uint32_t)storage_capacity;
  ring->mask = ring->capacity - 1U;
  ring->head = 0U;
  ring->tail = 0U;
  return ZS407_CORE_OK;
}

size_t zs407_spsc_ring_available(const zs407_spsc_ring_t *ring)
{
  if (ring == NULL) {
    return 0U;
  }
  uint32_t head = load_acquire(&ring->head);
  uint32_t tail = load_relaxed(&ring->tail);
  return (size_t)(head - tail);
}

size_t zs407_spsc_ring_free(const zs407_spsc_ring_t *ring)
{
  return ring == NULL ? 0U :
      (size_t)ring->capacity - zs407_spsc_ring_available(ring);
}

static void copy_into_ring(zs407_spsc_ring_t *ring, uint32_t head,
                           const uint8_t *input, size_t count)
{
  size_t first = ring->capacity - (head & ring->mask);
  if (first > count) {
    first = count;
  }
  memcpy(&ring->data[head & ring->mask], input, first);
  memcpy(ring->data, &input[first], count - first);
}

size_t zs407_spsc_ring_write(zs407_spsc_ring_t *ring,
                             const uint8_t *input, size_t input_length)
{
  if (ring == NULL || input == NULL || input_length == 0U) {
    return 0U;
  }
  uint32_t head = load_relaxed(&ring->head);
  uint32_t tail = load_acquire(&ring->tail);
  size_t free_bytes = ring->capacity - (head - tail);
  size_t count = input_length < free_bytes ? input_length : free_bytes;
  copy_into_ring(ring, head, input, count);
  store_release(&ring->head, head + (uint32_t)count);
  return count;
}

size_t zs407_spsc_ring_read(zs407_spsc_ring_t *ring,
                            uint8_t *output, size_t output_capacity)
{
  if (ring == NULL || output == NULL || output_capacity == 0U) {
    return 0U;
  }
  uint32_t tail = load_relaxed(&ring->tail);
  uint32_t head = load_acquire(&ring->head);
  size_t available = head - tail;
  size_t count = output_capacity < available ? output_capacity : available;
  size_t first = ring->capacity - (tail & ring->mask);
  if (first > count) {
    first = count;
  }
  memcpy(output, &ring->data[tail & ring->mask], first);
  memcpy(&output[first], ring->data, count - first);
  store_release(&ring->tail, tail + (uint32_t)count);
  return count;
}
