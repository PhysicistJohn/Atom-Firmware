/* SPDX-License-Identifier: GPL-3.0-or-later */
#define _POSIX_C_SOURCE 200809L
#include "modern/core/zs407_passive.h"
#include "modern/core/zs407_trace_codec.h"
#include "modern/core/zs407_waveform.h"

#include <stdio.h>
#include <time.h>

static uint64_t nanoseconds(void)
{
  struct timespec value;
  (void)clock_gettime(CLOCK_MONOTONIC, &value);
  return (uint64_t)value.tv_sec * UINT64_C(1000000000) +
         (uint64_t)value.tv_nsec;
}

static zs407_db32_t tone(uint16_t index, uint16_t bin)
{
  uint32_t phase = (uint32_t)(((uint64_t)index * bin << 32) / 1024U);
  return zs407_db32_saturate(-1500 + zs407_sine_q15(phase) / 48);
}

int main(void)
{
  zs407_db32_t trace[450];
  for (uint16_t i = 0U; i < 450U; ++i) {
    trace[i] = (zs407_db32_t)(-3200 + (int32_t)(i / 5U));
  }
  trace[100] = -1600;
  trace[300] = -1200;
  zs407_trace_chunk_payload_t header = {
      .trace_id = 407U,
      .sequence = 1U,
      .flags = ZS407_TRACE_CHUNK_COMPLETE,
      .start_index = 0U,
      .point_count = 450U,
      .total_points = 450U,
      .validity_bytes = 0U,
      .start_hz = UINT64_C(100000000),
      .frequency_step_numerator_hz = UINT64_C(449000000),
      .frequency_step_denominator = 449U,
      .rbw_hz = 10000U,
      .enbw_hz = 11200U,
      .timestamp_us = UINT64_C(1000000),
      .path = 0U,
      .detector = 0U,
      .power_scale_db = ZS407_TRACE_DB_SCALE,
      .reserved = 0U};
  uint8_t payload[ZS407_PROTOCOL_MAX_PAYLOAD];
  size_t delta_length = 0U;
  if (zs407_trace_chunk_delta_encode(
          &header, trace, payload, sizeof(payload), &delta_length) !=
      ZS407_CORE_OK) {
    return 2;
  }

  const uint32_t codec_iterations = 20000U;
  uint64_t start = nanoseconds();
  uint32_t checksum = 0U;
  for (uint32_t i = 0U; i < codec_iterations; ++i) {
    size_t length = 0U;
    if (zs407_trace_chunk_delta_encode(
            &header, trace, payload, sizeof(payload), &length) !=
        ZS407_CORE_OK) {
      return 2;
    }
    checksum += (uint32_t)length + payload[length - 1U];
  }
  uint64_t codec_elapsed = nanoseconds() - start;

  zs407_adaptive_window_payload_t windows[8];
  size_t window_count = 0U;
  size_t candidate_count = 0U;
  const uint32_t planner_iterations = 20000U;
  start = nanoseconds();
  for (uint32_t i = 0U; i < planner_iterations; ++i) {
    if (zs407_adaptive_plan(
            i, i, trace, 450U, UINT64_C(100000000),
            UINT64_C(449000000), 449U, -3200, 192, 4U, 201U,
            windows, 8U, &window_count, &candidate_count) != ZS407_CORE_OK) {
      return 2;
    }
    checksum += (uint32_t)window_count;
  }
  uint64_t planner_elapsed = nanoseconds() - start;

  int16_t real[1024];
  int16_t imag[1024];
  zs407_zero_span_capture_t capture;
  if (zs407_zero_span_capture_init(&capture, real, 1024U) != ZS407_CORE_OK) {
    return 2;
  }
  zs407_capture_config_t config = {
      .trigger_level_db32 = -2000,
      .hysteresis_db32 = 32,
      .sample_count = 1024U,
      .pretrigger_samples = 0U,
      .nominal_period_us = 100U,
      .maximum_jitter_us = 1U};
  const uint32_t fft_iterations = 1000U;
  start = nanoseconds();
  for (uint32_t iteration = 0U; iteration < fft_iterations; ++iteration) {
    if (zs407_zero_span_capture_arm(
            &capture, iteration, iteration, &config) != ZS407_CORE_OK) {
      return 2;
    }
    for (uint16_t i = 0U; i < 1024U; ++i) {
      if (zs407_zero_span_capture_feed(
              &capture, tone(i, 73U),
              UINT64_C(1000000) + (uint64_t)i * 100U) != ZS407_CORE_OK) {
        return 2;
      }
    }
    zs407_capture_summary_payload_t summary;
    if (zs407_zero_span_capture_analyze(
            &capture, imag, 1024U, &summary) != ZS407_CORE_OK) {
      return 2;
    }
    checksum += summary.peak_bin;
  }
  uint64_t fft_elapsed = nanoseconds() - start;

  zs407_monotonic_clock_t clock;
  uint64_t timestamp = 0U;
  if (zs407_monotonic_clock_init(&clock, 407U, 10000U) != ZS407_CORE_OK) {
    return 2;
  }
  const uint32_t clock_iterations = 1000000U;
  start = nanoseconds();
  for (uint32_t i = 0U; i < clock_iterations; ++i) {
    if (zs407_monotonic_clock_update(&clock, i, &timestamp) !=
        ZS407_CORE_OK) {
      return 2;
    }
  }
  uint64_t clock_elapsed = nanoseconds() - start;
  checksum += (uint32_t)timestamp;

  size_t raw_length = zs407_trace_chunk_payload_size(450U);
  printf("passive_trace_raw_bytes=%zu\n", raw_length);
  printf("passive_trace_delta_bytes=%zu\n", delta_length);
  printf("passive_trace_ratio=%.3f\n", (double)delta_length / raw_length);
  printf("passive_delta_encode_ns=%llu\n",
         (unsigned long long)(codec_elapsed / codec_iterations));
  printf("passive_adaptive_plan_ns=%llu\n",
         (unsigned long long)(planner_elapsed / planner_iterations));
  printf("passive_fft1024_pipeline_ns=%llu\n",
         (unsigned long long)(fft_elapsed / fft_iterations));
  printf("passive_clock_update_ns=%llu\n",
         (unsigned long long)(clock_elapsed / clock_iterations));
  printf("passive_benchmark_checksum=%u\n", checksum);
  return 0;
}
