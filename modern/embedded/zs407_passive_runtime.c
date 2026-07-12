/* SPDX-License-Identifier: GPL-3.0-or-later */
#include "zs407_passive_runtime.h"

#include "ch.h"

#include "../core/zs407_measurements.h"
#include "../core/zs407_protocol.h"
#include "../core/zs407_trace_codec.h"
#include "../core/zs407_waveform.h"

#include <string.h>

#define ZS407_PASSIVE_CLOCK_ID UINT32_C(0x5a533430)
#define ZS407_PASSIVE_STREAM_ID UINT32_C(0x04070001)
#define ZS407_PASSIVE_STREAM_FLAG 0x04U

static uint8_t *stream_frame_storage;
static zs407_stream_slot_t stream_slot;
static zs407_monotonic_clock_t device_clock;
static zs407_acquisition_ledger_t acquisition_ledger;
static zs407_zero_span_capture_t zero_span_capture;
static int16_t *capture_fft_workspace;
static size_t capture_scratch_capacity;
static zs407_capture_summary_payload_t last_capture_summary;
static bool last_capture_summary_valid;
static bool runtime_initialized;
typedef struct {
  zs407_clock_snapshot_payload_t clock;
  zs407_acquisition_status_payload_t acquisition;
  uint8_t capture_state;
} runtime_snapshot_t;
static runtime_snapshot_t runtime_status_snapshots[2];
static uint32_t active_status_snapshot;
/* Deliberately private, immutable-zero gates in the unqualified image. */
static volatile bool passive_hardware_qualified;
static volatile bool passive_stream_qualified;
static volatile bool passive_capture_qualified;

#if CH_CFG_USE_HEAP || CH_CFG_USE_MEMCORE
#error "passive stream heap lease requires ChibiOS heap and memcore to be disabled"
#endif
extern uint8_t __heap_base__;
extern uint8_t __heap_end__;

static void refresh_status_snapshot(void)
{
  uint32_t next = __atomic_load_n(&active_status_snapshot,
                                  __ATOMIC_RELAXED) ^ 1U;
  runtime_snapshot_t *status = &runtime_status_snapshots[next];
  memset(status, 0, sizeof(*status));
  zs407_monotonic_clock_snapshot(
      &device_clock, device_clock.last_raw_tick, &status->clock);
  zs407_acquisition_ledger_snapshot(
      &acquisition_ledger, &status->acquisition);
  status->capture_state = zero_span_capture.state;
  __atomic_store_n(&active_status_snapshot, next, __ATOMIC_RELEASE);
}

zs407_core_status_t zs407_passive_runtime_init(
    int16_t *capture_samples, int16_t *fft_workspace,
    size_t scratch_capacity)
{
  if (runtime_initialized) {
    return ZS407_CORE_OK;
  }
  if (capture_samples == NULL || fft_workspace == NULL ||
      scratch_capacity < ZS407_PASSIVE_MAX_CAPTURE_POINTS) {
    return ZS407_CORE_INVALID_ARGUMENT;
  }
  if (zs407_monotonic_clock_init(&device_clock, ZS407_PASSIVE_CLOCK_ID,
                                  CH_CFG_ST_FREQUENCY) != ZS407_CORE_OK ||
      zs407_zero_span_capture_init(&zero_span_capture, capture_samples,
                                   scratch_capacity) != ZS407_CORE_OK) {
    return ZS407_CORE_INVALID_ARGUMENT;
  }
  capture_fft_workspace = fft_workspace;
  capture_scratch_capacity = scratch_capacity;
  zs407_acquisition_ledger_init(&acquisition_ledger,
                                ZS407_PASSIVE_STREAM_ID,
                                ZS407_ACQUISITION_LOCKED);
  runtime_initialized = true;
  refresh_status_snapshot();
  return ZS407_CORE_OK;
}

static zs407_core_status_t encode_trace_frame(
    zs407_stream_slot_t *slot,
    uint32_t trace_id, uint64_t timestamp_us, uint32_t duration_us,
    const float *samples, uint16_t point_count,
    uint64_t start_hz, uint64_t stop_hz, uint32_t rbw_hz,
    uint32_t enbw_hz, uint8_t path, uint8_t detector)
{
  (void)duration_us;
  if (slot == NULL || samples == NULL || point_count == 0U ||
      point_count > ZS407_PROTOCOL_MAX_TRACE_CHUNK_POINTS ||
      stop_hz < start_hz) {
    return ZS407_CORE_INVALID_ARGUMENT;
  }
  size_t payload_length = zs407_trace_chunk_payload_size(point_count);
  if (payload_length == 0U) {
    return ZS407_CORE_INVALID_ARGUMENT;
  }
  uint8_t *frame_storage = NULL;
  size_t frame_capacity = 0U;
  zs407_core_status_t status = zs407_stream_slot_producer_begin(
      slot, &frame_storage, &frame_capacity);
  if (status != ZS407_CORE_OK) {
    return status;
  }
  if (frame_capacity < ZS407_FRAME_OVERHEAD_BYTES) {
    zs407_stream_slot_producer_abort(slot);
    return ZS407_CORE_BUFFER_TOO_SMALL;
  }
  if (zero_span_capture.state != ZS407_CAPTURE_IDLE &&
      zero_span_capture.state != ZS407_CAPTURE_ANALYZED) {
    zs407_stream_slot_producer_abort(slot);
    return ZS407_CORE_BUFFER_TOO_SMALL;
  }
  zs407_db32_t *trace_samples = zero_span_capture.samples;
  for (uint16_t i = 0U; i < point_count; ++i) {
    trace_samples[i] = ZS407_TRACE_INVALID_SAMPLE;
    (void)zs407_db32_from_double(samples[i], &trace_samples[i]);
  }
  size_t available_payload = frame_capacity - ZS407_FRAME_OVERHEAD_BYTES;
  if (available_payload > ZS407_PROTOCOL_MAX_PAYLOAD) {
    available_payload = ZS407_PROTOCOL_MAX_PAYLOAD;
  }
  zs407_frame_t frame = {
      .version = ZS407_PROTOCOL_VERSION,
      .flags = ZS407_PASSIVE_STREAM_FLAG,
      .request_id = (uint16_t)trace_id,
      .command = ZS407_COMMAND_SWEEP_DATA,
      .payload = NULL,
      .payload_length = (uint16_t)available_payload};
  uint8_t *payload = NULL;
  status = zs407_frame_begin(&frame, frame_storage, frame_capacity, &payload);
  if (status != ZS407_CORE_OK) {
    zs407_stream_slot_producer_abort(slot);
    return status;
  }
  zs407_trace_chunk_payload_t header = {
      .trace_id = trace_id,
      .sequence = (uint16_t)trace_id,
      .flags = ZS407_TRACE_CHUNK_COMPLETE |
               ZS407_TRACE_CHUNK_MONOTONIC_TIME,
      .start_index = 0U,
      .point_count = point_count,
      .total_points = point_count,
      .validity_bytes = (uint16_t)((point_count + 7U) / 8U),
      .start_hz = start_hz,
      .frequency_step_numerator_hz = stop_hz - start_hz,
      .frequency_step_denominator = point_count > 1U ? point_count - 1U : 1U,
      .rbw_hz = rbw_hz,
      .enbw_hz = enbw_hz,
      .timestamp_us = timestamp_us,
      .path = path,
      .detector = detector,
      .power_scale_db = ZS407_TRACE_DB_SCALE,
      .reserved = 0U};
  size_t encoded_payload = 0U;
  status = zs407_trace_chunk_delta_encode(
      &header, trace_samples, payload, available_payload, &encoded_payload);
  if (status != ZS407_CORE_OK || encoded_payload >= payload_length) {
    status = zs407_trace_chunk_encode(
        &header, trace_samples, payload, available_payload, &encoded_payload);
  }
  if (status != ZS407_CORE_OK || encoded_payload > UINT16_MAX ||
      zs407_frame_resize_payload(frame_storage, frame_capacity,
                                 (uint16_t)encoded_payload) != ZS407_CORE_OK) {
    zs407_stream_slot_producer_abort(slot);
    return status != ZS407_CORE_OK ? status : ZS407_CORE_BAD_FRAME;
  }
  size_t frame_length = 0U;
  status = zs407_frame_finish(frame_storage, frame_capacity, &frame_length);
  if (status != ZS407_CORE_OK ||
      zs407_stream_slot_producer_commit(slot, frame_length) !=
          ZS407_CORE_OK) {
    zs407_stream_slot_producer_abort(slot);
    return status != ZS407_CORE_OK ? status : ZS407_CORE_BAD_FRAME;
  }
  return ZS407_CORE_OK;
}

static void capture_zero_span_sweep(const float *samples, uint16_t point_count,
                                    uint64_t start_us, uint32_t duration_us)
{
  if ((zero_span_capture.state != ZS407_CAPTURE_ARMED &&
       zero_span_capture.state != ZS407_CAPTURE_COLLECTING) ||
      samples == NULL || point_count < 2U || duration_us == 0U) {
    return;
  }
  uint32_t denominator = point_count - 1U;
  for (uint16_t i = 0U; i < point_count; ++i) {
    zs407_db32_t sample = ZS407_TRACE_INVALID_SAMPLE;
    (void)zs407_db32_from_double(samples[i], &sample);
    uint64_t timestamp = start_us + (uint64_t)duration_us * i / denominator;
    if (zs407_zero_span_capture_feed(
            &zero_span_capture, sample, timestamp) != ZS407_CORE_OK ||
        zero_span_capture.state == ZS407_CAPTURE_READY) {
      break;
    }
  }
  if ((zero_span_capture.flags & ZS407_CAPTURE_TRIGGERED) != 0U) {
    zero_span_capture.flags |= ZS407_CAPTURE_TIMESTAMPS_INTERPOLATED;
  }
  if (zero_span_capture.state == ZS407_CAPTURE_READY &&
      zs407_zero_span_capture_analyze(
          &zero_span_capture, capture_fft_workspace,
          capture_scratch_capacity, &last_capture_summary) == ZS407_CORE_OK) {
    __atomic_store_n(&last_capture_summary_valid, true, __ATOMIC_RELEASE);
  }
}

void zs407_passive_runtime_on_sweep_complete(
    uint32_t completion_tick, uint32_t duration_us,
    const float *samples, uint16_t point_count,
    uint64_t start_hz, uint64_t stop_hz, uint32_t rbw_hz,
    uint32_t enbw_hz, uint8_t path, uint8_t detector,
    bool zero_span)
{
  if (!runtime_initialized) {
    return;
  }
  uint64_t completion_us = 0U;
  bool valid = samples != NULL && point_count > 0U &&
               point_count <= ZS407_PROTOCOL_MAX_TRACE_CHUNK_POINTS &&
               stop_hz >= start_hz && duration_us != 0U &&
               zs407_monotonic_clock_update(
                   &device_clock, completion_tick, &completion_us) ==
                   ZS407_CORE_OK;
  uint64_t start_us = completion_us > duration_us
                          ? completion_us - duration_us : 0U;
  uint32_t trace_id = zs407_acquisition_record_complete(
      &acquisition_ledger, start_us, duration_us, point_count, valid);
  if (valid && zero_span) {
    capture_zero_span_sweep(samples, point_count, start_us, duration_us);
  }
  if (acquisition_ledger.state != ZS407_ACQUISITION_STREAMING) {
    refresh_status_snapshot();
    return;
  }
  bool published = valid &&
      encode_trace_frame(&stream_slot, trace_id, start_us, duration_us, samples,
                         point_count, start_hz, stop_hz, rbw_hz,
                         enbw_hz, path, detector) == ZS407_CORE_OK;
  zs407_acquisition_record_publication(&acquisition_ledger, published);
  refresh_status_snapshot();
}

void zs407_passive_runtime_status(zs407_passive_runtime_status_t *status)
{
  if (status == NULL) {
    return;
  }
  uint32_t active = __atomic_load_n(&active_status_snapshot,
                                    __ATOMIC_ACQUIRE);
  const runtime_snapshot_t *snapshot = &runtime_status_snapshots[active];
  memset(status, 0, sizeof(*status));
  status->initialized = runtime_initialized;
  status->hardware_qualified = passive_hardware_qualified;
  status->stream_qualified = passive_stream_qualified;
  status->capture_qualified = passive_capture_qualified;
  status->clock = snapshot->clock;
  status->acquisition = snapshot->acquisition;
  status->capture_state = snapshot->capture_state;
  status->capture_summary_valid = __atomic_load_n(
      &last_capture_summary_valid, __ATOMIC_ACQUIRE);
  if (status->capture_summary_valid) {
    status->capture_summary = last_capture_summary;
  }
  if (!runtime_initialized) {
    return;
  }
  uint32_t raw_tick = chVTGetSystemTimeX();
  uint32_t elapsed_ticks = raw_tick - status->clock.raw_tick;
  if (elapsed_ticks <= UINT32_MAX / 2U) {
    uint64_t elapsed_us =
        ((uint64_t)elapsed_ticks / CH_CFG_ST_FREQUENCY) * UINT64_C(1000000) +
        ((uint64_t)elapsed_ticks % CH_CFG_ST_FREQUENCY) * UINT64_C(1000000) /
            CH_CFG_ST_FREQUENCY;
    if (status->clock.timestamp_us <= UINT64_MAX - elapsed_us) {
      status->clock.timestamp_us += elapsed_us;
      status->clock.raw_tick = raw_tick;
    }
  }
  status->slot_committed_frames = __atomic_load_n(
      &stream_slot.committed_frames, __ATOMIC_RELAXED);
  status->slot_consumed_frames = __atomic_load_n(
      &stream_slot.consumed_frames, __ATOMIC_RELAXED);
  status->slot_dropped_frames = __atomic_load_n(
      &stream_slot.dropped_frames, __ATOMIC_RELAXED);
}

zs407_core_status_t zs407_passive_runtime_start_stream(void)
{
  if (!runtime_initialized) {
    return ZS407_CORE_INVALID_ARGUMENT;
  }
  if (!passive_hardware_qualified || !passive_stream_qualified) {
    return ZS407_CORE_NOT_QUALIFIED;
  }
  if (zero_span_capture.state != ZS407_CAPTURE_IDLE &&
      zero_span_capture.state != ZS407_CAPTURE_ANALYZED) {
    return ZS407_CORE_OUT_OF_RANGE;
  }
  if (stream_frame_storage == NULL) {
    size_t unused_ram = (size_t)(&__heap_end__ - &__heap_base__);
    if (unused_ram < ZS407_FRAME_MAX_BYTES) {
      return ZS407_CORE_BUFFER_TOO_SMALL;
    }
    stream_frame_storage = &__heap_base__;
    if (zs407_stream_slot_init(&stream_slot, stream_frame_storage,
                               ZS407_FRAME_MAX_BYTES) != ZS407_CORE_OK) {
      stream_frame_storage = NULL;
      return ZS407_CORE_BUFFER_TOO_SMALL;
    }
  }
  acquisition_ledger.state = ZS407_ACQUISITION_STREAMING;
  refresh_status_snapshot();
  return ZS407_CORE_OK;
}

zs407_core_status_t zs407_passive_runtime_arm_capture(
    uint32_t capture_id, const zs407_capture_config_t *config)
{
  if (!runtime_initialized || config == NULL) {
    return ZS407_CORE_INVALID_ARGUMENT;
  }
  if (!passive_hardware_qualified || !passive_capture_qualified) {
    return ZS407_CORE_NOT_QUALIFIED;
  }
  if (acquisition_ledger.state == ZS407_ACQUISITION_STREAMING) {
    return ZS407_CORE_OUT_OF_RANGE;
  }
  __atomic_store_n(&last_capture_summary_valid, false, __ATOMIC_RELEASE);
  zs407_core_status_t status = zs407_zero_span_capture_arm(
      &zero_span_capture, capture_id, acquisition_ledger.next_sequence,
      config);
  refresh_status_snapshot();
  return status;
}

bool zs407_passive_runtime_take_frame(const uint8_t **data, size_t *length)
{
  return runtime_initialized && stream_frame_storage != NULL &&
         zs407_stream_slot_consumer_acquire(&stream_slot, data, length);
}

void zs407_passive_runtime_release_frame(void)
{
  if (runtime_initialized) {
    zs407_stream_slot_consumer_release(&stream_slot);
  }
}

static zs407_db32_t selftest_tone(uint16_t index)
{
  uint32_t phase = (uint32_t)(((uint64_t)index * 11U << 32) / 256U);
  return zs407_db32_saturate(-1500 + zs407_sine_q15(phase) / 48);
}

uint32_t zs407_passive_runtime_selftest(void)
{
  if (!runtime_initialized) {
    return UINT32_C(1) << 0;
  }
  uint32_t failures = 0U;
  zs407_monotonic_clock_t clock;
  uint64_t first = 0U;
  uint64_t second = 0U;
  if (zs407_monotonic_clock_init(&clock, 1U, CH_CFG_ST_FREQUENCY) !=
          ZS407_CORE_OK ||
      zs407_monotonic_clock_update(&clock, UINT32_C(0xffffff00), &first) !=
          ZS407_CORE_OK ||
      zs407_monotonic_clock_update(&clock, UINT32_C(0x100), &second) !=
          ZS407_CORE_OK || second <= first) {
    failures |= UINT32_C(1) << 1;
  }

  static const float trace[8] = {
      -100.0f, -99.5f, -99.0f, -98.5f,
      -98.0f, -97.5f, -97.0f, -96.5f};
  uint8_t selftest_storage[128];
  zs407_stream_slot_t selftest_slot;
  if (zs407_stream_slot_init(&selftest_slot, selftest_storage,
                             sizeof(selftest_storage)) != ZS407_CORE_OK ||
      encode_trace_frame(&selftest_slot, 407U, UINT64_C(1000000), 700U,
                         trace, 8U,
                         UINT64_C(100000000), UINT64_C(107000000),
                         10000U, 11200U, 0U, 0U) != ZS407_CORE_OK) {
    failures |= UINT32_C(1) << 2;
  } else {
    const uint8_t *frame_data = NULL;
    size_t frame_length = 0U;
    zs407_frame_t frame;
    zs407_trace_chunk_payload_t header;
    zs407_db32_t decoded_samples[8];
    if (!zs407_stream_slot_consumer_acquire(
            &selftest_slot, &frame_data, &frame_length) ||
        zs407_frame_decode(frame_data, frame_length, &frame) !=
            ZS407_CORE_OK || frame.command != ZS407_COMMAND_SWEEP_DATA ||
        zs407_trace_chunk_decode_samples(
            frame.payload, frame.payload_length, decoded_samples, 8U,
            &header) != ZS407_CORE_OK || header.trace_id != 407U ||
        (header.flags & ZS407_TRACE_CHUNK_DELTA_ENCODED) == 0U ||
        decoded_samples[7] != -3088) {
      failures |= UINT32_C(1) << 3;
    }
    zs407_stream_slot_consumer_release(&selftest_slot);
  }

  zs407_capture_config_t config = {
      .trigger_level_db32 = -2000,
      .hysteresis_db32 = 32,
      .sample_count = 256U,
      .pretrigger_samples = 0U,
      .nominal_period_us = 100U,
      .maximum_jitter_us = 1U};
  if (zs407_zero_span_capture_arm(
          &zero_span_capture, 256U, 1U, &config) != ZS407_CORE_OK) {
    failures |= UINT32_C(1) << 4;
  } else {
    for (uint16_t i = 0U; i < 256U; ++i) {
      if (zs407_zero_span_capture_feed(
              &zero_span_capture, selftest_tone(i),
              UINT64_C(2000000) + (uint64_t)i * 100U) != ZS407_CORE_OK) {
        failures |= UINT32_C(1) << 5;
        break;
      }
    }
    zs407_capture_summary_payload_t summary;
    if (zero_span_capture.state != ZS407_CAPTURE_READY ||
        zs407_zero_span_capture_analyze(
            &zero_span_capture, capture_fft_workspace,
            capture_scratch_capacity, &summary) != ZS407_CORE_OK ||
        summary.peak_bin != 11U || summary.discontinuities != 0U) {
      failures |= UINT32_C(1) << 6;
    }
  }
  zs407_zero_span_capture_reset(&zero_span_capture);
  __atomic_store_n(&last_capture_summary_valid, false, __ATOMIC_RELEASE);
  refresh_status_snapshot();
  return failures;
}
