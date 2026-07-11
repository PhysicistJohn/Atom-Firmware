/* SPDX-License-Identifier: GPL-3.0-or-later */
#ifndef ZS407_MEASUREMENTS_H
#define ZS407_MEASUREMENTS_H

#include "zs407_core.h"

enum {
  ZS407_MEASUREMENT_HAS_GAPS = UINT32_C(1) << 0,
  ZS407_MEASUREMENT_POWER_VALID = UINT32_C(1) << 1,
  ZS407_MEASUREMENT_OBW_VALID = UINT32_C(1) << 2,
  ZS407_MEASUREMENT_PEAK_INTERPOLATED = UINT32_C(1) << 3,
  ZS407_MEASUREMENT_NOISE_VALID = UINT32_C(1) << 4
};

typedef struct {
  uint16_t peak_index;
  int16_t peak_offset_q15;
  zs407_db32_t peak_db32;
  zs407_db32_t noise_db32;
  zs407_db32_t integrated_power_dbm32;
  uint16_t occupied_start_index;
  uint16_t occupied_stop_index;
  uint16_t valid_points;
  uint32_t flags;
} zs407_measurement_summary_t;

zs407_core_status_t zs407_db32_from_double(double db,
                                           zs407_db32_t *result);
double zs407_db32_to_double(zs407_db32_t value);

zs407_core_status_t zs407_summarize_trace(
    const zs407_db32_t *samples, size_t count, uint32_t bin_width_hz,
    uint32_t enbw_hz, uint16_t occupied_basis_points,
    zs407_db32_t *scratch, size_t scratch_count,
    zs407_measurement_summary_t *summary);

#endif /* ZS407_MEASUREMENTS_H */
