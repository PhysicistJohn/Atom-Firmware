/* SPDX-License-Identifier: GPL-3.0-or-later */
#ifndef ZS407_CORE_H
#define ZS407_CORE_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "../generated/zs407_contract.h"

typedef int16_t zs407_db32_t;

typedef enum {
  ZS407_CORE_OK = ZS407_STATUS_OK,
  ZS407_CORE_INVALID_ARGUMENT = ZS407_STATUS_INVALID_ARGUMENT,
  ZS407_CORE_OUT_OF_RANGE = ZS407_STATUS_OUT_OF_RANGE,
  ZS407_CORE_BUFFER_TOO_SMALL = ZS407_STATUS_BUFFER_TOO_SMALL,
  ZS407_CORE_BAD_FRAME = ZS407_STATUS_BAD_FRAME,
  ZS407_CORE_UNSUPPORTED = ZS407_STATUS_UNSUPPORTED,
  ZS407_CORE_NOT_QUALIFIED = ZS407_STATUS_NOT_QUALIFIED
} zs407_core_status_t;

typedef struct {
  uint64_t start_hz;
  uint64_t stop_hz;
  uint16_t point_count;
} zs407_sweep_request_t;

typedef struct {
  uint64_t current_hz;
  uint64_t whole_step_hz;
  uint32_t remainder_hz;
  uint32_t denominator;
  uint32_t error;
  uint16_t index;
  uint16_t point_count;
} zs407_frequency_dda_t;

typedef struct {
  uint64_t frequency_hz;
  zs407_db32_t correction_db32;
} zs407_correction_point_t;

typedef struct {
  const zs407_correction_point_t *points;
  size_t count;
  size_t segment;
} zs407_correction_cursor_t;

zs407_core_status_t zs407_frequency_dda_init(
    zs407_frequency_dda_t *dda, const zs407_sweep_request_t *request);
bool zs407_frequency_dda_next(zs407_frequency_dda_t *dda,
                              uint64_t *frequency_hz);

zs407_db32_t zs407_db32_saturate(int32_t value);

zs407_core_status_t zs407_correction_cursor_init(
    zs407_correction_cursor_t *cursor,
    const zs407_correction_point_t *points, size_t count);
zs407_core_status_t zs407_correction_at(
    zs407_correction_cursor_t *cursor, uint64_t frequency_hz,
    zs407_db32_t *correction_db32);

zs407_core_status_t zs407_quantile_db32(const zs407_db32_t *samples,
                                        size_t count, uint16_t quantile_q16,
                                        zs407_db32_t *scratch,
                                        size_t scratch_count,
                                        zs407_db32_t *result);

zs407_core_status_t zs407_parabolic_peak_offset_q15(
    zs407_db32_t left, zs407_db32_t center, zs407_db32_t right,
    int16_t *offset_q15);

#endif /* ZS407_CORE_H */
