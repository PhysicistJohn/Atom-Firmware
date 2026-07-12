/* SPDX-License-Identifier: GPL-3.0-or-later */
#ifndef ZS407_PASSIVE_H
#define ZS407_PASSIVE_H

#include "zs407_core.h"

#define ZS407_PASSIVE_MAX_WINDOWS 8U
#define ZS407_PASSIVE_MIN_CAPTURE_POINTS 256U
#define ZS407_PASSIVE_MAX_CAPTURE_POINTS 1024U

enum {
  ZS407_CLOCK_RELATIVE = UINT32_C(1) << 0,
  ZS407_CLOCK_MONOTONIC = UINT32_C(1) << 1,
  ZS407_CLOCK_WRAP_OBSERVED = UINT32_C(1) << 2,
  ZS407_CLOCK_REGRESSION_OBSERVED = UINT32_C(1) << 3
};

typedef struct {
  uint64_t epoch_ticks;
  uint64_t last_timestamp_us;
  uint32_t tick_frequency_hz;
  uint32_t last_raw_tick;
  uint32_t clock_id;
  uint32_t flags;
  bool initialized;
} zs407_monotonic_clock_t;

zs407_core_status_t zs407_monotonic_clock_init(
    zs407_monotonic_clock_t *clock, uint32_t clock_id,
    uint32_t tick_frequency_hz);
zs407_core_status_t zs407_monotonic_clock_update(
    zs407_monotonic_clock_t *clock, uint32_t raw_tick,
    uint64_t *timestamp_us);
void zs407_monotonic_clock_snapshot(
    const zs407_monotonic_clock_t *clock, uint32_t raw_tick,
    zs407_clock_snapshot_payload_t *snapshot);

typedef enum {
  ZS407_ACQUISITION_LOCKED = 0,
  ZS407_ACQUISITION_IDLE = 1,
  ZS407_ACQUISITION_STREAMING = 2,
  ZS407_ACQUISITION_CAPTURE = 3
} zs407_acquisition_state_t;

typedef struct {
  uint32_t stream_id;
  uint32_t next_sequence;
  uint32_t completed_sweeps;
  uint32_t published_sweeps;
  uint32_t dropped_sweeps;
  uint32_t invalid_sweeps;
  uint64_t last_start_us;
  uint32_t last_duration_us;
  uint16_t last_point_count;
  uint8_t state;
  uint8_t flags;
} zs407_acquisition_ledger_t;

void zs407_acquisition_ledger_init(zs407_acquisition_ledger_t *ledger,
                                   uint32_t stream_id,
                                   zs407_acquisition_state_t state);
uint32_t zs407_acquisition_record_complete(
    zs407_acquisition_ledger_t *ledger, uint64_t start_us,
    uint32_t duration_us, uint16_t point_count, bool valid);
void zs407_acquisition_record_publication(
    zs407_acquisition_ledger_t *ledger, bool published);
void zs407_acquisition_ledger_snapshot(
    const zs407_acquisition_ledger_t *ledger,
    zs407_acquisition_status_payload_t *snapshot);

typedef enum {
  ZS407_SLOT_EMPTY = 0,
  ZS407_SLOT_WRITING = 1,
  ZS407_SLOT_READY = 2,
  ZS407_SLOT_READING = 3
} zs407_stream_slot_state_t;

typedef struct {
  uint8_t *storage;
  uint32_t capacity;
  uint32_t length;
  uint32_t state;
  uint32_t committed_frames;
  uint32_t consumed_frames;
  uint32_t dropped_frames;
} zs407_stream_slot_t;

zs407_core_status_t zs407_stream_slot_init(
    zs407_stream_slot_t *slot, uint8_t *storage, size_t storage_capacity);
zs407_core_status_t zs407_stream_slot_producer_begin(
    zs407_stream_slot_t *slot, uint8_t **storage, size_t *capacity);
zs407_core_status_t zs407_stream_slot_producer_commit(
    zs407_stream_slot_t *slot, size_t length);
void zs407_stream_slot_producer_abort(zs407_stream_slot_t *slot);
bool zs407_stream_slot_consumer_acquire(
    zs407_stream_slot_t *slot, const uint8_t **data, size_t *length);
void zs407_stream_slot_consumer_release(zs407_stream_slot_t *slot);

enum {
  ZS407_ADAPTIVE_PLAN_TRUNCATED = UINT16_C(1) << 0,
  ZS407_ADAPTIVE_PLAN_MERGED = UINT16_C(1) << 1
};

zs407_core_status_t zs407_adaptive_plan(
    uint32_t plan_id, uint32_t source_trace_id,
    const zs407_db32_t *samples, size_t count,
    uint64_t start_hz, uint64_t frequency_step_numerator_hz,
    uint32_t frequency_step_denominator, zs407_db32_t noise_floor,
    zs407_db32_t minimum_prominence, uint16_t radius,
    uint16_t refinement_points, zs407_adaptive_window_payload_t *windows,
    size_t window_capacity, size_t *window_count,
    size_t *candidate_count);

typedef enum {
  ZS407_CAPTURE_IDLE = 0,
  ZS407_CAPTURE_ARMED = 1,
  ZS407_CAPTURE_COLLECTING = 2,
  ZS407_CAPTURE_READY = 3,
  ZS407_CAPTURE_ANALYZED = 4
} zs407_capture_state_t;

enum {
  ZS407_CAPTURE_TRIGGERED = UINT32_C(1) << 0,
  ZS407_CAPTURE_TIMING_VALID = UINT32_C(1) << 1,
  ZS407_CAPTURE_PRETRIGGER_ESTIMATED = UINT32_C(1) << 2,
  ZS407_CAPTURE_TIMING_DISCONTINUITY = UINT32_C(1) << 3,
  ZS407_CAPTURE_FFT_COMPLETE = UINT32_C(1) << 4,
  ZS407_CAPTURE_DC_REMOVED = UINT32_C(1) << 5,
  ZS407_CAPTURE_HANN_WINDOWED = UINT32_C(1) << 6
};

typedef struct {
  zs407_db32_t trigger_level_db32;
  zs407_db32_t hysteresis_db32;
  uint16_t sample_count;
  uint16_t pretrigger_samples;
  uint32_t nominal_period_us;
  uint32_t maximum_jitter_us;
} zs407_capture_config_t;

typedef struct {
  int16_t *samples;
  uint16_t capacity;
  uint16_t start_index;
  uint16_t stored_samples;
  uint16_t trigger_index;
  uint8_t state;
  bool have_previous;
  zs407_db32_t previous_sample;
  zs407_capture_config_t config;
  uint32_t capture_id;
  uint32_t sequence;
  uint32_t flags;
  uint32_t minimum_delta_us;
  uint32_t maximum_delta_us;
  uint32_t discontinuities;
  uint32_t invalid_samples;
  uint64_t trigger_timestamp_us;
  uint64_t first_timestamp_us;
  uint64_t last_timestamp_us;
} zs407_zero_span_capture_t;

zs407_core_status_t zs407_zero_span_capture_init(
    zs407_zero_span_capture_t *capture, int16_t *sample_storage,
    size_t sample_capacity);
zs407_core_status_t zs407_zero_span_capture_arm(
    zs407_zero_span_capture_t *capture, uint32_t capture_id,
    uint32_t sequence, const zs407_capture_config_t *config);
zs407_core_status_t zs407_zero_span_capture_feed(
    zs407_zero_span_capture_t *capture, zs407_db32_t sample,
    uint64_t timestamp_us);
zs407_core_status_t zs407_zero_span_capture_feed_sweep(
    zs407_zero_span_capture_t *capture, const zs407_db32_t *samples,
    size_t sample_count, uint64_t sweep_start_us,
    uint32_t sweep_duration_us);
zs407_core_status_t zs407_zero_span_capture_analyze(
    zs407_zero_span_capture_t *capture, int16_t *fft_workspace,
    size_t workspace_capacity, zs407_capture_summary_payload_t *summary);
void zs407_zero_span_capture_reset(zs407_zero_span_capture_t *capture);

#endif /* ZS407_PASSIVE_H */
