/* SPDX-License-Identifier: GPL-3.0-or-later */
#include "modern/core/zs407_spsc.h"

#include <pthread.h>
#include <sched.h>
#include <stdint.h>
#include <stdio.h>

#define TRANSFER_BYTES (2U * 1024U * 1024U)

static uint8_t storage[256];
static zs407_spsc_ring_t ring;
static uint32_t producer_done;
static uint32_t failure;

static uint8_t pattern(size_t offset)
{
  uint32_t value = (uint32_t)offset;
  value ^= value >> 7;
  value *= UINT32_C(0x45d9f3b);
  return (uint8_t)(value ^ (value >> 16));
}

static void *producer(void *argument)
{
  (void)argument;
  size_t offset = 0U;
  uint8_t buffer[97];
  while (offset < TRANSFER_BYTES) {
    size_t count = sizeof(buffer);
    if (count > TRANSFER_BYTES - offset) {
      count = TRANSFER_BYTES - offset;
    }
    for (size_t i = 0U; i < count; ++i) {
      buffer[i] = pattern(offset + i);
    }
    size_t written = zs407_spsc_ring_write(&ring, buffer, count);
    offset += written;
    if (written == 0U) {
      sched_yield();
    }
  }
  __atomic_store_n(&producer_done, 1U, __ATOMIC_RELEASE);
  return NULL;
}

static void *consumer(void *argument)
{
  (void)argument;
  size_t offset = 0U;
  uint8_t buffer[83];
  while (offset < TRANSFER_BYTES) {
    size_t count = zs407_spsc_ring_read(&ring, buffer, sizeof(buffer));
    if (count == 0U) {
      if (__atomic_load_n(&producer_done, __ATOMIC_ACQUIRE) != 0U &&
          zs407_spsc_ring_available(&ring) == 0U) {
        __atomic_store_n(&failure, 1U, __ATOMIC_RELAXED);
        break;
      }
      sched_yield();
      continue;
    }
    for (size_t i = 0U; i < count; ++i) {
      if (buffer[i] != pattern(offset + i)) {
        __atomic_store_n(&failure, 2U, __ATOMIC_RELAXED);
        return NULL;
      }
    }
    offset += count;
  }
  return NULL;
}

int main(void)
{
  if (zs407_spsc_ring_init(&ring, storage, sizeof(storage)) !=
      ZS407_CORE_OK) {
    return 2;
  }
  pthread_t producer_thread;
  pthread_t consumer_thread;
  if (pthread_create(&producer_thread, NULL, producer, NULL) != 0 ||
      pthread_create(&consumer_thread, NULL, consumer, NULL) != 0) {
    return 2;
  }
  if (pthread_join(producer_thread, NULL) != 0 ||
      pthread_join(consumer_thread, NULL) != 0) {
    return 2;
  }
  uint32_t result = __atomic_load_n(&failure, __ATOMIC_RELAXED);
  if (result != 0U) {
    fprintf(stderr, "SPSC threaded failure=%u\n", result);
    return 1;
  }
  puts("ZS407 SPSC threaded stress: passed");
  return 0;
}
