/* SPDX-License-Identifier: GPL-3.0-or-later */
#ifndef ZS407_PASSIVE_RUNTIME_H
#define ZS407_PASSIVE_RUNTIME_H

#include "../core/zs407_passive.h"

typedef struct {
  bool initialized;
  bool hardware_qualified;
  bool stream_qualified;
  bool capture_qualified;
  zs407_clock_snapshot_payload_t clock;
  zs407_acquisition_status_payload_t acquisition;
  uint32_t slot_committed_frames;
  uint32_t slot_consumed_frames;
  uint32_t slot_dropped_frames;
  uint8_t capture_state;
  bool capture_summary_valid;
  zs407_capture_summary_payload_t capture_summary;
} zs407_passive_runtime_status_t;

zs407_core_status_t zs407_passive_runtime_init(
    int16_t *capture_samples, int16_t *fft_workspace,
    size_t scratch_capacity);
void zs407_passive_runtime_on_sweep_complete(
    uint32_t completion_tick, uint32_t duration_us,
    const float *samples, uint16_t point_count,
    uint64_t start_hz, uint64_t stop_hz, uint32_t rbw_hz,
    uint32_t enbw_hz, uint8_t path, uint8_t detector,
    bool zero_span);
void zs407_passive_runtime_status(zs407_passive_runtime_status_t *status);
zs407_core_status_t zs407_passive_runtime_start_stream(void);
zs407_core_status_t zs407_passive_runtime_arm_capture(
    uint32_t capture_id, const zs407_capture_config_t *config);
bool zs407_passive_runtime_take_frame(const uint8_t **data, size_t *length);
void zs407_passive_runtime_release_frame(void);
uint32_t zs407_passive_runtime_selftest(void);

#endif /* ZS407_PASSIVE_RUNTIME_H */
