/* SPDX-License-Identifier: GPL-3.0-or-later */
#ifndef ZS407_RF_LAB_H
#define ZS407_RF_LAB_H

#include "zs407_core.h"

typedef struct {
  uint64_t requested_hz;
  uint64_t actual_hz;
  uint32_t fraction;
  uint16_t vco_count_estimate;
  uint8_t integer;
  uint8_t band;
  uint8_t divider;
  bool vco_estimate_in_range;
} zs407_si4468_hop_plan_t;

zs407_core_status_t zs407_si4468_hop_plan(
    uint64_t frequency_hz, uint64_t reference_hz_x100,
    zs407_si4468_hop_plan_t *plan);

typedef struct {
  uint64_t requested_hz;
  uint64_t actual_hz;
  uint32_t register0;
  uint32_t register1;
  uint16_t integer;
  uint16_t fraction;
  uint16_t modulus;
  uint8_t divider;
  uint8_t divider_code;
} zs407_max2871_plan_t;

zs407_core_status_t zs407_max2871_plan(
    uint64_t frequency_hz, uint64_t pfd_hz_x100, uint16_t modulus,
    zs407_max2871_plan_t *plan);

typedef struct {
  uint16_t first_index;
  uint16_t last_index;
  uint16_t peak_index;
} zs407_refinement_window_t;

zs407_core_status_t zs407_select_refinement_windows(
    const zs407_db32_t *samples, size_t count, zs407_db32_t noise_floor,
    zs407_db32_t minimum_prominence, uint16_t radius,
    zs407_refinement_window_t *windows, size_t window_capacity,
    size_t *window_count);

#endif /* ZS407_RF_LAB_H */
