/* SPDX-License-Identifier: GPL-3.0-or-later */
#include "zs407_passive.h"

#include "zs407_fft.h"
#include "zs407_waveform.h"

#include <limits.h>
#include <string.h>

static uint32_t saturating_increment(uint32_t value)
{
  return value == UINT32_MAX ? UINT32_MAX : value + 1U;
}

static uint64_t ticks_to_microseconds(uint64_t ticks, uint32_t frequency_hz)
{
  uint64_t seconds = ticks / frequency_hz;
  uint64_t remainder = ticks % frequency_hz;
  if (seconds > UINT64_MAX / UINT64_C(1000000)) {
    return UINT64_MAX;
  }
  return seconds * UINT64_C(1000000) +
         remainder * UINT64_C(1000000) / frequency_hz;
}

zs407_core_status_t zs407_monotonic_clock_init(
    zs407_monotonic_clock_t *clock, uint32_t clock_id,
    uint32_t tick_frequency_hz)
{
  if (clock == NULL || tick_frequency_hz == 0U ||
      tick_frequency_hz > UINT32_C(1000000000)) {
    return ZS407_CORE_INVALID_ARGUMENT;
  }
  memset(clock, 0, sizeof(*clock));
  clock->clock_id = clock_id;
  clock->tick_frequency_hz = tick_frequency_hz;
  clock->flags = ZS407_CLOCK_RELATIVE | ZS407_CLOCK_MONOTONIC;
  return ZS407_CORE_OK;
}

zs407_core_status_t zs407_monotonic_clock_update(
    zs407_monotonic_clock_t *clock, uint32_t raw_tick,
    uint64_t *timestamp_us)
{
  if (clock == NULL || timestamp_us == NULL ||
      clock->tick_frequency_hz == 0U) {
    return ZS407_CORE_INVALID_ARGUMENT;
  }
  if (!clock->initialized) {
    clock->initialized = true;
  } else if (raw_tick < clock->last_raw_tick) {
    uint32_t backward = clock->last_raw_tick - raw_tick;
    if (backward <= UINT32_MAX / 2U) {
      clock->flags |= ZS407_CLOCK_REGRESSION_OBSERVED;
      return ZS407_CORE_BAD_FRAME;
    }
    clock->epoch_ticks += UINT64_C(1) << 32;
    clock->flags |= ZS407_CLOCK_WRAP_OBSERVED;
  }
  uint64_t extended_ticks = clock->epoch_ticks + raw_tick;
  uint64_t converted = ticks_to_microseconds(
      extended_ticks, clock->tick_frequency_hz);
  if (converted < clock->last_timestamp_us) {
    clock->flags |= ZS407_CLOCK_REGRESSION_OBSERVED;
    return ZS407_CORE_BAD_FRAME;
  }
  clock->last_raw_tick = raw_tick;
  clock->last_timestamp_us = converted;
  *timestamp_us = converted;
  return ZS407_CORE_OK;
}

void zs407_monotonic_clock_snapshot(
    const zs407_monotonic_clock_t *clock, uint32_t raw_tick,
    zs407_clock_snapshot_payload_t *snapshot)
{
  if (clock == NULL || snapshot == NULL) {
    return;
  }
  snapshot->clock_id = clock->clock_id;
  snapshot->flags = clock->flags;
  snapshot->timestamp_us = clock->last_timestamp_us;
  snapshot->tick_frequency_hz = clock->tick_frequency_hz;
  snapshot->raw_tick = raw_tick;
}

void zs407_acquisition_ledger_init(zs407_acquisition_ledger_t *ledger,
                                   uint32_t stream_id,
                                   zs407_acquisition_state_t state)
{
  if (ledger != NULL) {
    memset(ledger, 0, sizeof(*ledger));
    ledger->stream_id = stream_id;
    ledger->state = (uint8_t)state;
  }
}

uint32_t zs407_acquisition_record_complete(
    zs407_acquisition_ledger_t *ledger, uint64_t start_us,
    uint32_t duration_us, uint16_t point_count, bool valid)
{
  if (ledger == NULL) {
    return 0U;
  }
  uint32_t sequence = ledger->next_sequence++;
  ledger->completed_sweeps = saturating_increment(ledger->completed_sweeps);
  if (!valid) {
    ledger->invalid_sweeps = saturating_increment(ledger->invalid_sweeps);
  }
  ledger->last_start_us = start_us;
  ledger->last_duration_us = duration_us;
  ledger->last_point_count = point_count;
  return sequence;
}

void zs407_acquisition_record_publication(
    zs407_acquisition_ledger_t *ledger, bool published)
{
  if (ledger == NULL) {
    return;
  }
  if (published) {
    ledger->published_sweeps =
        saturating_increment(ledger->published_sweeps);
  } else {
    ledger->dropped_sweeps = saturating_increment(ledger->dropped_sweeps);
  }
}

void zs407_acquisition_ledger_snapshot(
    const zs407_acquisition_ledger_t *ledger,
    zs407_acquisition_status_payload_t *snapshot)
{
  if (ledger == NULL || snapshot == NULL) {
    return;
  }
  snapshot->stream_id = ledger->stream_id;
  snapshot->next_sequence = ledger->next_sequence;
  snapshot->completed_sweeps = ledger->completed_sweeps;
  snapshot->published_sweeps = ledger->published_sweeps;
  snapshot->dropped_sweeps = ledger->dropped_sweeps;
  snapshot->invalid_sweeps = ledger->invalid_sweeps;
  snapshot->last_start_us = ledger->last_start_us;
  snapshot->last_duration_us = ledger->last_duration_us;
  snapshot->last_point_count = ledger->last_point_count;
  snapshot->state = ledger->state;
  snapshot->flags = ledger->flags;
}

zs407_core_status_t zs407_stream_slot_init(
    zs407_stream_slot_t *slot, uint8_t *storage, size_t storage_capacity)
{
  if (slot == NULL || storage == NULL || storage_capacity == 0U ||
      storage_capacity > UINT32_MAX) {
    return ZS407_CORE_INVALID_ARGUMENT;
  }
  memset(slot, 0, sizeof(*slot));
  slot->storage = storage;
  slot->capacity = (uint32_t)storage_capacity;
  return ZS407_CORE_OK;
}

zs407_core_status_t zs407_stream_slot_producer_begin(
    zs407_stream_slot_t *slot, uint8_t **storage, size_t *capacity)
{
  if (slot == NULL || storage == NULL || capacity == NULL ||
      slot->storage == NULL) {
    return ZS407_CORE_INVALID_ARGUMENT;
  }
  uint32_t expected = ZS407_SLOT_EMPTY;
  if (!__atomic_compare_exchange_n(&slot->state, &expected,
                                   ZS407_SLOT_WRITING, false,
                                   __ATOMIC_ACQUIRE, __ATOMIC_RELAXED)) {
    __atomic_add_fetch(&slot->dropped_frames, 1U, __ATOMIC_RELAXED);
    return ZS407_CORE_BUFFER_TOO_SMALL;
  }
  *storage = slot->storage;
  *capacity = slot->capacity;
  return ZS407_CORE_OK;
}

zs407_core_status_t zs407_stream_slot_producer_commit(
    zs407_stream_slot_t *slot, size_t length)
{
  if (slot == NULL || length == 0U || length > slot->capacity ||
      __atomic_load_n(&slot->state, __ATOMIC_RELAXED) !=
          ZS407_SLOT_WRITING) {
    return ZS407_CORE_INVALID_ARGUMENT;
  }
  slot->length = (uint32_t)length;
  __atomic_add_fetch(&slot->committed_frames, 1U, __ATOMIC_RELAXED);
  __atomic_store_n(&slot->state, ZS407_SLOT_READY, __ATOMIC_RELEASE);
  return ZS407_CORE_OK;
}

void zs407_stream_slot_producer_abort(zs407_stream_slot_t *slot)
{
  if (slot != NULL &&
      __atomic_load_n(&slot->state, __ATOMIC_RELAXED) ==
          ZS407_SLOT_WRITING) {
    slot->length = 0U;
    __atomic_store_n(&slot->state, ZS407_SLOT_EMPTY, __ATOMIC_RELEASE);
  }
}

bool zs407_stream_slot_consumer_acquire(
    zs407_stream_slot_t *slot, const uint8_t **data, size_t *length)
{
  if (slot == NULL || data == NULL || length == NULL) {
    return false;
  }
  uint32_t expected = ZS407_SLOT_READY;
  if (!__atomic_compare_exchange_n(&slot->state, &expected,
                                   ZS407_SLOT_READING, false,
                                   __ATOMIC_ACQUIRE, __ATOMIC_RELAXED)) {
    return false;
  }
  *data = slot->storage;
  *length = slot->length;
  return true;
}

void zs407_stream_slot_consumer_release(zs407_stream_slot_t *slot)
{
  if (slot != NULL &&
      __atomic_load_n(&slot->state, __ATOMIC_RELAXED) ==
          ZS407_SLOT_READING) {
    slot->length = 0U;
    __atomic_add_fetch(&slot->consumed_frames, 1U, __ATOMIC_RELAXED);
    __atomic_store_n(&slot->state, ZS407_SLOT_EMPTY, __ATOMIC_RELEASE);
  }
}

typedef struct {
  uint16_t index;
  int32_t strength;
} adaptive_candidate_t;

static uint64_t frequency_at(uint64_t start_hz, uint64_t numerator,
                             uint32_t denominator, uint16_t index)
{
  if (index != 0U && numerator > UINT64_MAX / index) {
    return UINT64_MAX;
  }
  uint64_t offset = numerator * index / denominator;
  return start_hz > UINT64_MAX - offset ? UINT64_MAX : start_hz + offset;
}

zs407_core_status_t zs407_adaptive_plan(
    uint32_t plan_id, uint32_t source_trace_id,
    const zs407_db32_t *samples, size_t count,
    uint64_t start_hz, uint64_t frequency_step_numerator_hz,
    uint32_t frequency_step_denominator, zs407_db32_t noise_floor,
    zs407_db32_t minimum_prominence, uint16_t radius,
    uint16_t refinement_points, zs407_adaptive_window_payload_t *windows,
    size_t window_capacity, size_t *window_count,
    size_t *candidate_count)
{
  if (samples == NULL || windows == NULL || window_count == NULL ||
      candidate_count == NULL || count < 3U || count > UINT16_MAX ||
      frequency_step_denominator == 0U || minimum_prominence < 0 ||
      refinement_points < 2U || window_capacity == 0U ||
      window_capacity > ZS407_PASSIVE_MAX_WINDOWS) {
    return ZS407_CORE_INVALID_ARGUMENT;
  }
  *window_count = 0U;
  *candidate_count = 0U;
  adaptive_candidate_t candidates[ZS407_PASSIVE_MAX_WINDOWS];
  size_t retained = 0U;
  int32_t threshold = (int32_t)noise_floor + minimum_prominence;
  for (size_t index = 1U; index + 1U < count; ++index) {
    if (samples[index] == ZS407_TRACE_INVALID_SAMPLE ||
        samples[index] < threshold || samples[index] < samples[index - 1U] ||
        samples[index] < samples[index + 1U] ||
        (samples[index] == samples[index - 1U] &&
         samples[index] == samples[index + 1U])) {
      continue;
    }
    (*candidate_count)++;
    adaptive_candidate_t candidate = {
        (uint16_t)index, (int32_t)samples[index] - noise_floor};
    size_t insertion = 0U;
    while (insertion < retained &&
           (candidates[insertion].strength > candidate.strength ||
            (candidates[insertion].strength == candidate.strength &&
             candidates[insertion].index < candidate.index))) {
      insertion++;
    }
    if (insertion >= window_capacity) {
      continue;
    }
    size_t move_end = retained < window_capacity ? retained :
                      window_capacity - 1U;
    while (move_end > insertion) {
      candidates[move_end] = candidates[move_end - 1U];
      move_end--;
    }
    candidates[insertion] = candidate;
    if (retained < window_capacity) {
      retained++;
    }
  }

  uint16_t common_flags = *candidate_count > window_capacity
                              ? ZS407_ADAPTIVE_PLAN_TRUNCATED : 0U;
  for (size_t candidate_index = 0U;
       candidate_index < retained; ++candidate_index) {
    uint16_t peak = candidates[candidate_index].index;
    uint16_t first = peak > radius ? (uint16_t)(peak - radius) : 0U;
    size_t expanded_last = (size_t)peak + radius;
    uint16_t last = (uint16_t)(expanded_last < count ? expanded_last :
                               count - 1U);
    size_t merge_index = *window_count;
    for (size_t i = 0U; i < *window_count; ++i) {
      if (!(last + 1U < windows[i].first_index ||
            first > windows[i].last_index + 1U)) {
        merge_index = i;
        break;
      }
    }
    if (merge_index < *window_count) {
      if (first < windows[merge_index].first_index) {
        windows[merge_index].first_index = first;
      }
      if (last > windows[merge_index].last_index) {
        windows[merge_index].last_index = last;
      }
      windows[merge_index].flags |= ZS407_ADAPTIVE_PLAN_MERGED;
      continue;
    }
    zs407_adaptive_window_payload_t *window = &windows[*window_count];
    memset(window, 0, sizeof(*window));
    window->plan_id = plan_id;
    window->source_trace_id = source_trace_id;
    window->first_index = first;
    window->last_index = last;
    window->peak_index = peak;
    window->priority = (uint16_t)candidate_index;
    window->point_count = refinement_points;
    window->flags = common_flags;
    (*window_count)++;
  }
  for (size_t i = 0U; i < *window_count; ++i) {
    windows[i].priority = (uint16_t)i;
    windows[i].flags |= common_flags;
    windows[i].start_hz = frequency_at(
        start_hz, frequency_step_numerator_hz,
        frequency_step_denominator, windows[i].first_index);
    windows[i].stop_hz = frequency_at(
        start_hz, frequency_step_numerator_hz,
        frequency_step_denominator, windows[i].last_index);
    if (windows[i].start_hz == UINT64_MAX ||
        windows[i].stop_hz == UINT64_MAX) {
      return ZS407_CORE_OUT_OF_RANGE;
    }
  }
  return ZS407_CORE_OK;
}

static bool capture_count_valid(uint16_t count)
{
  return count >= ZS407_PASSIVE_MIN_CAPTURE_POINTS &&
         count <= ZS407_PASSIVE_MAX_CAPTURE_POINTS &&
         (count & (count - 1U)) == 0U;
}

zs407_core_status_t zs407_zero_span_capture_init(
    zs407_zero_span_capture_t *capture, int16_t *sample_storage,
    size_t sample_capacity)
{
  if (capture == NULL || sample_storage == NULL ||
      sample_capacity < ZS407_PASSIVE_MIN_CAPTURE_POINTS ||
      sample_capacity > UINT16_MAX) {
    return ZS407_CORE_INVALID_ARGUMENT;
  }
  memset(capture, 0, sizeof(*capture));
  capture->samples = sample_storage;
  capture->capacity = (uint16_t)sample_capacity;
  return ZS407_CORE_OK;
}

zs407_core_status_t zs407_zero_span_capture_arm(
    zs407_zero_span_capture_t *capture, uint32_t capture_id,
    uint32_t sequence, const zs407_capture_config_t *config)
{
  if (capture == NULL || config == NULL || capture->samples == NULL ||
      !capture_count_valid(config->sample_count) ||
      config->sample_count > capture->capacity ||
      config->pretrigger_samples >= config->sample_count ||
      config->hysteresis_db32 < 0 || config->nominal_period_us == 0U) {
    return ZS407_CORE_INVALID_ARGUMENT;
  }
  int16_t *storage = capture->samples;
  uint16_t capacity = capture->capacity;
  memset(capture, 0, sizeof(*capture));
  capture->samples = storage;
  capture->capacity = capacity;
  capture->capture_id = capture_id;
  capture->sequence = sequence;
  capture->config = *config;
  capture->minimum_delta_us = UINT32_MAX;
  capture->state = ZS407_CAPTURE_ARMED;
  return ZS407_CORE_OK;
}

static void capture_pretrigger_push(zs407_zero_span_capture_t *capture,
                                    zs407_db32_t sample)
{
  uint16_t pretrigger = capture->config.pretrigger_samples;
  if (pretrigger == 0U) {
    return;
  }
  uint16_t index = (uint16_t)((capture->start_index +
                               capture->stored_samples) %
                              capture->config.sample_count);
  capture->samples[index] = sample;
  if (capture->stored_samples < pretrigger) {
    capture->stored_samples++;
  } else {
    capture->start_index = (uint16_t)((capture->start_index + 1U) %
                                      capture->config.sample_count);
  }
}

static void capture_append(zs407_zero_span_capture_t *capture,
                           zs407_db32_t sample)
{
  uint16_t index = (uint16_t)((capture->start_index +
                               capture->stored_samples) %
                              capture->config.sample_count);
  capture->samples[index] = sample;
  capture->stored_samples++;
}

static void capture_observe_delta(zs407_zero_span_capture_t *capture,
                                  uint64_t timestamp_us)
{
  if (capture->last_timestamp_us == 0U ||
      timestamp_us <= capture->last_timestamp_us) {
    if (capture->last_timestamp_us != 0U) {
      capture->discontinuities =
          saturating_increment(capture->discontinuities);
      capture->flags |= ZS407_CAPTURE_TIMING_DISCONTINUITY;
    }
    return;
  }
  uint64_t wide_delta = timestamp_us - capture->last_timestamp_us;
  uint32_t delta = wide_delta > UINT32_MAX ? UINT32_MAX :
                   (uint32_t)wide_delta;
  if (delta < capture->minimum_delta_us) {
    capture->minimum_delta_us = delta;
  }
  if (delta > capture->maximum_delta_us) {
    capture->maximum_delta_us = delta;
  }
  uint32_t nominal = capture->config.nominal_period_us;
  uint32_t difference = delta > nominal ? delta - nominal : nominal - delta;
  if (difference > capture->config.maximum_jitter_us) {
    capture->discontinuities =
        saturating_increment(capture->discontinuities);
    capture->flags |= ZS407_CAPTURE_TIMING_DISCONTINUITY;
  }
}

zs407_core_status_t zs407_zero_span_capture_feed(
    zs407_zero_span_capture_t *capture, zs407_db32_t sample,
    uint64_t timestamp_us)
{
  if (capture == NULL || capture->samples == NULL || timestamp_us == 0U ||
      (capture->state != ZS407_CAPTURE_ARMED &&
       capture->state != ZS407_CAPTURE_COLLECTING)) {
    return ZS407_CORE_INVALID_ARGUMENT;
  }
  if (sample == ZS407_TRACE_INVALID_SAMPLE) {
    capture->invalid_samples =
        saturating_increment(capture->invalid_samples);
    capture->have_previous = false;
    return ZS407_CORE_OK;
  }

  if (capture->state == ZS407_CAPTURE_ARMED) {
    int32_t low_threshold =
        (int32_t)capture->config.trigger_level_db32 -
        capture->config.hysteresis_db32;
    bool triggered = sample >= capture->config.trigger_level_db32 &&
                     (!capture->have_previous ||
                      capture->previous_sample <= low_threshold);
    if (!triggered) {
      capture_pretrigger_push(capture, sample);
      capture->previous_sample = sample;
      capture->have_previous = true;
      return ZS407_CORE_OK;
    }
    capture->trigger_index = capture->stored_samples;
    capture->trigger_timestamp_us = timestamp_us;
    uint64_t pretrigger_span =
        (uint64_t)capture->trigger_index *
        capture->config.nominal_period_us;
    capture->first_timestamp_us = timestamp_us > pretrigger_span
                                      ? timestamp_us - pretrigger_span : 1U;
    capture->flags = ZS407_CAPTURE_TRIGGERED | ZS407_CAPTURE_TIMING_VALID;
    if (capture->trigger_index != 0U) {
      capture->flags |= ZS407_CAPTURE_PRETRIGGER_ESTIMATED;
    }
    capture->state = ZS407_CAPTURE_COLLECTING;
    capture_append(capture, sample);
    capture->last_timestamp_us = timestamp_us;
  } else {
    capture_observe_delta(capture, timestamp_us);
    capture_append(capture, sample);
    capture->last_timestamp_us = timestamp_us;
  }
  capture->previous_sample = sample;
  capture->have_previous = true;
  if (capture->stored_samples == capture->config.sample_count) {
    capture->state = ZS407_CAPTURE_READY;
  }
  return ZS407_CORE_OK;
}

zs407_core_status_t zs407_zero_span_capture_feed_sweep(
    zs407_zero_span_capture_t *capture, const zs407_db32_t *samples,
    size_t sample_count, uint64_t sweep_start_us,
    uint32_t sweep_duration_us)
{
  if (capture == NULL || samples == NULL || sample_count < 2U ||
      sample_count > UINT16_MAX || sweep_start_us == 0U ||
      sweep_duration_us == 0U ||
      sweep_start_us > UINT64_MAX - sweep_duration_us) {
    return ZS407_CORE_INVALID_ARGUMENT;
  }
  uint64_t denominator = sample_count - 1U;
  for (size_t i = 0U; i < sample_count; ++i) {
    uint64_t timestamp = sweep_start_us +
                         (uint64_t)sweep_duration_us * i / denominator;
    zs407_core_status_t status = zs407_zero_span_capture_feed(
        capture, samples[i], timestamp);
    if (status != ZS407_CORE_OK) {
      return status;
    }
    if (capture->state == ZS407_CAPTURE_READY) {
      break;
    }
  }
  if ((capture->flags & ZS407_CAPTURE_TRIGGERED) != 0U) {
    capture->flags |= ZS407_CAPTURE_TIMESTAMPS_INTERPOLATED;
  }
  return ZS407_CORE_OK;
}

static uint8_t capture_log2(uint16_t points)
{
  uint8_t result = 0U;
  while (points > 1U) {
    points >>= 1;
    result++;
  }
  return result;
}

static uint32_t sample_period_ns(const zs407_zero_span_capture_t *capture)
{
  uint32_t denominator = capture->config.sample_count - 1U;
  uint64_t span = capture->last_timestamp_us - capture->first_timestamp_us;
  uint64_t value = (span / denominator) * 1000U +
                   (span % denominator) * 1000U / denominator;
  return value > UINT32_MAX ? UINT32_MAX : (uint32_t)value;
}

zs407_core_status_t zs407_zero_span_capture_analyze(
    zs407_zero_span_capture_t *capture, int16_t *fft_workspace,
    size_t workspace_capacity, zs407_capture_summary_payload_t *summary)
{
  if (capture == NULL || fft_workspace == NULL || summary == NULL ||
      capture->state != ZS407_CAPTURE_READY ||
      workspace_capacity < capture->config.sample_count ||
      fft_workspace == capture->samples) {
    return ZS407_CORE_INVALID_ARGUMENT;
  }
  uint16_t count = capture->config.sample_count;
  int64_t sum = 0;
  for (uint16_t i = 0U; i < count; ++i) {
    uint16_t source = (uint16_t)((capture->start_index + i) % count);
    fft_workspace[i] = capture->samples[source];
    sum += fft_workspace[i];
  }
  int32_t mean = (int32_t)(sum / count);
  int32_t maximum = 0;
  for (uint16_t i = 0U; i < count; ++i) {
    int32_t centered = (int32_t)fft_workspace[i] - mean;
    int32_t magnitude = centered < 0 ? -centered : centered;
    if (magnitude > maximum) {
      maximum = magnitude;
    }
  }
  if (maximum == 0) {
    maximum = 1;
  }
  for (uint16_t i = 0U; i < count; ++i) {
    int32_t centered = (int32_t)fft_workspace[i] - mean;
    int32_t normalized = (centered * INT32_C(30000)) / maximum;
    uint32_t phase = (uint32_t)(((uint64_t)i * UINT32_MAX) /
                                (count - 1U));
    int32_t cosine = zs407_sine_q15(phase + UINT32_C(0x40000000));
    int32_t window = (INT32_C(32767) - cosine) / 2;
    capture->samples[i] = zs407_q15_saturate(
        (normalized * window) / INT32_C(32768));
    fft_workspace[i] = 0;
  }
  zs407_core_status_t status = zs407_fft_q15(
      capture->samples, fft_workspace, capture_log2(count));
  if (status != ZS407_CORE_OK) {
    return status;
  }
  uint32_t peak_magnitude = 0U;
  uint16_t peak_bin = 0U;
  for (uint16_t i = 1U; i < count / 2U; ++i) {
    uint32_t magnitude = zs407_fft_magnitude_squared_q30(
        capture->samples[i], fft_workspace[i]);
    if (magnitude > peak_magnitude) {
      peak_magnitude = magnitude;
      peak_bin = i;
    }
  }
  capture->flags |= ZS407_CAPTURE_FFT_COMPLETE |
                    ZS407_CAPTURE_DC_REMOVED |
                    ZS407_CAPTURE_HANN_WINDOWED;
  memset(summary, 0, sizeof(*summary));
  summary->capture_id = capture->capture_id;
  summary->sequence = capture->sequence;
  summary->flags = capture->flags;
  summary->sample_count = count;
  summary->trigger_index = capture->trigger_index;
  summary->peak_bin = peak_bin;
  summary->first_timestamp_us = capture->first_timestamp_us;
  summary->last_timestamp_us = capture->last_timestamp_us;
  summary->sample_period_ns = sample_period_ns(capture);
  summary->minimum_delta_us = capture->minimum_delta_us == UINT32_MAX
                                  ? 0U : capture->minimum_delta_us;
  summary->maximum_delta_us = capture->maximum_delta_us;
  summary->discontinuities = capture->discontinuities;
  summary->peak_magnitude_q30 = peak_magnitude;
  capture->state = ZS407_CAPTURE_ANALYZED;
  return ZS407_CORE_OK;
}

void zs407_zero_span_capture_reset(zs407_zero_span_capture_t *capture)
{
  if (capture == NULL) {
    return;
  }
  int16_t *storage = capture->samples;
  uint16_t capacity = capture->capacity;
  memset(capture, 0, sizeof(*capture));
  capture->samples = storage;
  capture->capacity = capacity;
}
