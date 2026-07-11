/* SPDX-License-Identifier: GPL-3.0-or-later */
#ifndef ZS407_COMPACT_H
#define ZS407_COMPACT_H

#include "zs407_waveform.h"

zs407_core_status_t zs407_uleb128_encode(
    uint64_t value, uint8_t *output, size_t output_capacity,
    size_t *output_length);
zs407_core_status_t zs407_uleb128_decode(
    const uint8_t *input, size_t input_length, uint64_t *value,
    size_t *consumed);

zs407_core_status_t zs407_trace_delta_encode(
    const zs407_db32_t *samples, size_t sample_count,
    uint8_t *output, size_t output_capacity, size_t *output_length);
zs407_core_status_t zs407_trace_delta_decode(
    const uint8_t *input, size_t input_length,
    zs407_db32_t *samples, size_t sample_count);

zs407_core_status_t zs407_wave_events_compact_encode(
    const zs407_wave_event_t *events, size_t event_count,
    uint8_t *output, size_t output_capacity, size_t *output_length);
zs407_core_status_t zs407_wave_events_compact_decode(
    const uint8_t *input, size_t input_length,
    zs407_wave_event_t *events, size_t event_count);

#endif /* ZS407_COMPACT_H */
