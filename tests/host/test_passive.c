/* SPDX-License-Identifier: GPL-3.0-or-later */
#include "modern/core/zs407_passive.h"
#include "modern/core/zs407_waveform.h"

#include <pthread.h>
#include <sched.h>
#include <stdio.h>
#include <string.h>

#define CHECK(condition)                                                       \
  do {                                                                         \
    if (!(condition)) {                                                        \
      fprintf(stderr, "CHECK failed at %s:%d: %s\n", __FILE__, __LINE__,      \
              #condition);                                                     \
      return 1;                                                                \
    }                                                                          \
  } while (0)

static int test_clock(void)
{
  zs407_monotonic_clock_t clock;
  uint64_t first = 0U;
  uint64_t second = 0U;
  CHECK(zs407_monotonic_clock_init(&clock, 407U, 10000U) == ZS407_CORE_OK);
  CHECK(zs407_monotonic_clock_update(&clock, UINT32_C(0xffffff00), &first) ==
        ZS407_CORE_OK);
  CHECK(zs407_monotonic_clock_update(&clock, UINT32_C(0x00000100), &second) ==
        ZS407_CORE_OK);
  CHECK(second > first && second - first == 51200U);
  CHECK((clock.flags & ZS407_CLOCK_WRAP_OBSERVED) != 0U);
  CHECK(zs407_monotonic_clock_update(&clock, UINT32_C(0x00000080), &second) ==
        ZS407_CORE_BAD_FRAME);
  CHECK((clock.flags & ZS407_CLOCK_REGRESSION_OBSERVED) != 0U);
  zs407_clock_snapshot_payload_t snapshot = {0};
  zs407_monotonic_clock_snapshot(&clock, UINT32_C(0x100), &snapshot);
  CHECK(snapshot.clock_id == 407U && snapshot.tick_frequency_hz == 10000U);
  CHECK(snapshot.timestamp_us == clock.last_timestamp_us);
  CHECK(zs407_monotonic_clock_init(NULL, 1U, 1U) ==
        ZS407_CORE_INVALID_ARGUMENT);
  return 0;
}

static int test_ledger(void)
{
  zs407_acquisition_ledger_t ledger;
  zs407_acquisition_ledger_init(&ledger, 0x407U,
                                ZS407_ACQUISITION_STREAMING);
  CHECK(zs407_acquisition_record_complete(
            &ledger, UINT64_C(123456), 9000U, 450U, true) == 0U);
  CHECK(zs407_acquisition_record_complete(
            &ledger, UINT64_C(132456), 9100U, 450U, false) == 1U);
  zs407_acquisition_record_publication(&ledger, true);
  zs407_acquisition_record_publication(&ledger, false);
  CHECK(ledger.completed_sweeps == 2U && ledger.published_sweeps == 1U);
  CHECK(ledger.dropped_sweeps == 1U && ledger.invalid_sweeps == 1U);
  ledger.dropped_sweeps = UINT32_MAX;
  zs407_acquisition_record_publication(&ledger, false);
  CHECK(ledger.dropped_sweeps == UINT32_MAX);
  zs407_acquisition_status_payload_t snapshot = {0};
  zs407_acquisition_ledger_snapshot(&ledger, &snapshot);
  CHECK(snapshot.stream_id == 0x407U && snapshot.next_sequence == 2U);
  CHECK(snapshot.last_start_us == UINT64_C(132456));
  CHECK(snapshot.state == ZS407_ACQUISITION_STREAMING);
  return 0;
}

typedef struct {
  zs407_stream_slot_t slot;
  uint8_t storage[64];
  uint32_t frames;
  uint32_t failure;
} slot_stress_t;

static void *slot_producer(void *context)
{
  slot_stress_t *stress = (slot_stress_t *)context;
  for (uint32_t sequence = 0U; sequence < stress->frames; ++sequence) {
    uint8_t *storage = NULL;
    size_t capacity = 0U;
    while (zs407_stream_slot_producer_begin(
               &stress->slot, &storage, &capacity) != ZS407_CORE_OK) {
      sched_yield();
    }
    if (capacity < 8U) {
      stress->failure = 1U;
      zs407_stream_slot_producer_abort(&stress->slot);
      return NULL;
    }
    for (size_t i = 0U; i < 8U; ++i) {
      storage[i] = (uint8_t)(sequence >> ((i & 3U) * 8U));
    }
    if (zs407_stream_slot_producer_commit(&stress->slot, 8U) !=
        ZS407_CORE_OK) {
      stress->failure = 2U;
      return NULL;
    }
  }
  return NULL;
}

static void *slot_consumer(void *context)
{
  slot_stress_t *stress = (slot_stress_t *)context;
  for (uint32_t expected = 0U; expected < stress->frames;) {
    const uint8_t *data = NULL;
    size_t length = 0U;
    if (!zs407_stream_slot_consumer_acquire(
            &stress->slot, &data, &length)) {
      sched_yield();
      continue;
    }
    uint32_t first = (uint32_t)data[0] | ((uint32_t)data[1] << 8) |
                     ((uint32_t)data[2] << 16) | ((uint32_t)data[3] << 24);
    uint32_t second = (uint32_t)data[4] | ((uint32_t)data[5] << 8) |
                      ((uint32_t)data[6] << 16) | ((uint32_t)data[7] << 24);
    if (length != 8U || first != expected || second != expected) {
      stress->failure = 3U;
    }
    zs407_stream_slot_consumer_release(&stress->slot);
    if (stress->failure != 0U) {
      return NULL;
    }
    expected++;
  }
  return NULL;
}

static int test_slot(void)
{
  slot_stress_t stress = {.frames = 50000U};
  CHECK(zs407_stream_slot_init(&stress.slot, stress.storage,
                               sizeof(stress.storage)) == ZS407_CORE_OK);
  uint8_t *storage = NULL;
  size_t capacity = 0U;
  CHECK(zs407_stream_slot_producer_begin(&stress.slot, &storage, &capacity) ==
        ZS407_CORE_OK);
  CHECK(zs407_stream_slot_producer_begin(&stress.slot, &storage, &capacity) ==
        ZS407_CORE_BUFFER_TOO_SMALL);
  CHECK(stress.slot.dropped_frames == 1U);
  zs407_stream_slot_producer_abort(&stress.slot);

  pthread_t producer;
  pthread_t consumer;
  CHECK(pthread_create(&producer, NULL, slot_producer, &stress) == 0);
  CHECK(pthread_create(&consumer, NULL, slot_consumer, &stress) == 0);
  CHECK(pthread_join(producer, NULL) == 0);
  CHECK(pthread_join(consumer, NULL) == 0);
  CHECK(stress.failure == 0U);
  CHECK(stress.slot.committed_frames == stress.frames);
  CHECK(stress.slot.consumed_frames == stress.frames);
  CHECK(stress.slot.state == ZS407_SLOT_EMPTY);
  return 0;
}

static int test_adaptive_plan(void)
{
  zs407_db32_t samples[450];
  for (size_t i = 0U; i < 450U; ++i) {
    samples[i] = -3200;
  }
  samples[99] = -2000;
  samples[100] = -1000;
  samples[101] = -2100;
  samples[102] = -900;
  samples[103] = -2200;
  samples[299] = -2400;
  samples[300] = -800;
  samples[301] = -2300;
  zs407_adaptive_window_payload_t windows[4];
  size_t count = 0U;
  size_t candidates = 0U;
  CHECK(zs407_adaptive_plan(
            7U, 9U, samples, 450U, UINT64_C(100000000),
            UINT64_C(449000000), 449U, -3200, 320, 3U, 201U,
            windows, 4U, &count, &candidates) == ZS407_CORE_OK);
  CHECK(candidates == 3U && count == 2U);
  CHECK(windows[0].peak_index == 300U && windows[0].priority == 0U);
  CHECK(windows[0].start_hz == UINT64_C(397000000));
  CHECK(windows[0].stop_hz == UINT64_C(403000000));
  CHECK(windows[1].peak_index == 102U);
  CHECK(windows[1].first_index == 97U && windows[1].last_index == 105U);
  CHECK((windows[1].flags & ZS407_ADAPTIVE_PLAN_MERGED) != 0U);

  for (size_t i = 10U; i < 430U; i += 10U) {
    samples[i] = (zs407_db32_t)(-1500 + (int32_t)(i % 100U));
  }
  CHECK(zs407_adaptive_plan(
            8U, 10U, samples, 450U, 0U, UINT64_C(449000000), 449U,
            -3200, 320, 1U, 101U, windows, 4U, &count, &candidates) ==
        ZS407_CORE_OK);
  CHECK(candidates > 4U && count <= 4U);
  for (size_t i = 0U; i < count; ++i) {
    CHECK((windows[i].flags & ZS407_ADAPTIVE_PLAN_TRUNCATED) != 0U);
  }
  return 0;
}

static zs407_db32_t tone_sample(uint16_t index, uint16_t count,
                                uint16_t bin)
{
  uint32_t phase = (uint32_t)(((uint64_t)index * bin << 32) / count);
  int32_t value = -1500 + zs407_sine_q15(phase) / 48;
  return zs407_db32_saturate(value);
}

static int test_capture_fft(void)
{
  int16_t real[1024];
  int16_t imag[1024];
  zs407_zero_span_capture_t capture;
  CHECK(zs407_zero_span_capture_init(&capture, real, 1024U) ==
        ZS407_CORE_OK);
  const zs407_capture_config_t config = {
      .trigger_level_db32 = -2000,
      .hysteresis_db32 = 64,
      .sample_count = 1024U,
      .pretrigger_samples = 0U,
      .nominal_period_us = 100U,
      .maximum_jitter_us = 1U};
  CHECK(zs407_zero_span_capture_arm(&capture, 1024U, 17U, &config) ==
        ZS407_CORE_OK);
  for (uint16_t i = 0U; i < 1024U; ++i) {
    CHECK(zs407_zero_span_capture_feed(
              &capture, tone_sample(i, 1024U, 73U),
              UINT64_C(1000000) + (uint64_t)i * 100U) == ZS407_CORE_OK);
  }
  CHECK(capture.state == ZS407_CAPTURE_READY);
  zs407_capture_summary_payload_t summary;
  CHECK(zs407_zero_span_capture_analyze(
            &capture, imag, 1024U, &summary) == ZS407_CORE_OK);
  CHECK(capture.state == ZS407_CAPTURE_ANALYZED);
  CHECK(summary.sample_count == 1024U && summary.peak_bin == 73U);
  CHECK(summary.sample_period_ns == 100000U);
  CHECK(summary.minimum_delta_us == 100U &&
        summary.maximum_delta_us == 100U);
  CHECK(summary.discontinuities == 0U);
  CHECK((summary.flags & (ZS407_CAPTURE_TRIGGERED |
                          ZS407_CAPTURE_FFT_COMPLETE |
                          ZS407_CAPTURE_DC_REMOVED |
                          ZS407_CAPTURE_HANN_WINDOWED)) ==
        (ZS407_CAPTURE_TRIGGERED | ZS407_CAPTURE_FFT_COMPLETE |
         ZS407_CAPTURE_DC_REMOVED | ZS407_CAPTURE_HANN_WINDOWED));
  return 0;
}

static int test_capture_pretrigger_and_sweeps(void)
{
  int16_t real[256];
  int16_t imag[256];
  zs407_zero_span_capture_t capture;
  CHECK(zs407_zero_span_capture_init(&capture, real, 256U) ==
        ZS407_CORE_OK);
  const zs407_capture_config_t config = {
      .trigger_level_db32 = -2000,
      .hysteresis_db32 = 32,
      .sample_count = 256U,
      .pretrigger_samples = 16U,
      .nominal_period_us = 100U,
      .maximum_jitter_us = 2U};
  CHECK(zs407_zero_span_capture_arm(&capture, 256U, 18U, &config) ==
        ZS407_CORE_OK);
  for (uint16_t i = 0U; i < 40U; ++i) {
    CHECK(zs407_zero_span_capture_feed(
              &capture, -3000, UINT64_C(2000000) + (uint64_t)i * 100U) ==
          ZS407_CORE_OK);
  }
  CHECK(zs407_zero_span_capture_feed(&capture, -1500,
                                      UINT64_C(2004000)) == ZS407_CORE_OK);
  CHECK(capture.trigger_index == 16U);
  for (uint16_t i = 1U; capture.state != ZS407_CAPTURE_READY; ++i) {
    uint64_t timestamp = UINT64_C(2004000) + (uint64_t)i * 100U;
    if (i == 50U) {
      timestamp += 10U;
    }
    CHECK(zs407_zero_span_capture_feed(&capture,
                                       tone_sample(i, 256U, 11U),
                                       timestamp) == ZS407_CORE_OK);
  }
  zs407_capture_summary_payload_t summary;
  CHECK(zs407_zero_span_capture_analyze(
            &capture, imag, 256U, &summary) == ZS407_CORE_OK);
  CHECK(summary.trigger_index == 16U);
  CHECK((summary.flags & ZS407_CAPTURE_PRETRIGGER_ESTIMATED) != 0U);
  CHECK((summary.flags & ZS407_CAPTURE_TIMING_DISCONTINUITY) != 0U);
  CHECK(summary.discontinuities >= 1U);

  zs407_zero_span_capture_reset(&capture);
  zs407_capture_config_t no_pretrigger = config;
  no_pretrigger.pretrigger_samples = 0U;
  CHECK(zs407_zero_span_capture_arm(
            &capture, 257U, 19U, &no_pretrigger) == ZS407_CORE_OK);
  zs407_db32_t first[128];
  zs407_db32_t second[128];
  for (uint16_t i = 0U; i < 128U; ++i) {
    first[i] = tone_sample(i, 256U, 9U);
    second[i] = tone_sample((uint16_t)(i + 128U), 256U, 9U);
  }
  CHECK(zs407_zero_span_capture_feed_sweep(
            &capture, first, 128U, UINT64_C(3000000), 12700U) ==
        ZS407_CORE_OK);
  CHECK(zs407_zero_span_capture_feed_sweep(
            &capture, second, 128U, UINT64_C(3012800), 12700U) ==
        ZS407_CORE_OK);
  CHECK(capture.state == ZS407_CAPTURE_READY);
  CHECK(zs407_zero_span_capture_analyze(
            &capture, imag, 256U, &summary) == ZS407_CORE_OK);
  CHECK(summary.peak_bin == 9U && summary.discontinuities == 0U);
  return 0;
}

int main(void)
{
  CHECK(test_clock() == 0);
  CHECK(test_ledger() == 0);
  CHECK(test_slot() == 0);
  CHECK(test_adaptive_plan() == 0);
  CHECK(test_capture_fft() == 0);
  CHECK(test_capture_pretrigger_and_sweeps() == 0);
  puts("ZS407 passive acquisition: all tests passed");
  return 0;
}
