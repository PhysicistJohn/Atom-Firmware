/* SPDX-License-Identifier: GPL-3.0-or-later */
#ifndef ZS407_AWG_H
#define ZS407_AWG_H

#include "../core/zs407_waveform.h"

#define ZS407_AWG_SAMPLE_COUNT 256U
#define ZS407_AWG_MIN_SAMPLE_RATE_HZ 100U
#define ZS407_AWG_MAX_SAMPLE_RATE_HZ 200000U

typedef struct {
  uint32_t requested_frequency_millihz;
  uint32_t actual_frequency_millihz;
  uint32_t requested_sample_rate_hz;
  uint32_t actual_sample_rate_hz;
  uint32_t buffer_crc32;
  uint16_t amplitude;
  uint16_t offset;
  uint16_t sample_count;
  uint8_t shape;
  bool prepared;
  bool active;
  bool hardware_qualified;
} zs407_awg_status_t;

zs407_core_status_t zs407_awg_prepare(zs407_wave_shape_t shape,
                                      uint32_t frequency_millihz,
                                      uint32_t sample_rate_hz,
                                      uint16_t amplitude, uint16_t offset);
zs407_core_status_t zs407_awg_start(void);
void zs407_awg_stop(void);
void zs407_awg_get_status(zs407_awg_status_t *status);
uint32_t zs407_awg_selftest(void);

#endif /* ZS407_AWG_H */
