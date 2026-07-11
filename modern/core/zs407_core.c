/* SPDX-License-Identifier: GPL-3.0-or-later */
#include "zs407_core.h"

#include <limits.h>

zs407_core_status_t zs407_frequency_dda_init(
    zs407_frequency_dda_t *dda, const zs407_sweep_request_t *request)
{
  if (dda == NULL || request == NULL || request->point_count == 0U ||
      request->start_hz > request->stop_hz) {
    return ZS407_CORE_INVALID_ARGUMENT;
  }

  dda->current_hz = request->start_hz;
  dda->index = 0U;
  dda->point_count = request->point_count;
  dda->error = 0U;
  if (request->point_count == 1U) {
    dda->whole_step_hz = 0U;
    dda->remainder_hz = 0U;
    dda->denominator = 1U;
    return ZS407_CORE_OK;
  }

  uint64_t delta = request->stop_hz - request->start_hz;
  dda->denominator = (uint32_t)request->point_count - 1U;
  dda->whole_step_hz = delta / dda->denominator;
  dda->remainder_hz = (uint32_t)(delta % dda->denominator);
  return ZS407_CORE_OK;
}

bool zs407_frequency_dda_next(zs407_frequency_dda_t *dda,
                              uint64_t *frequency_hz)
{
  if (dda == NULL || frequency_hz == NULL || dda->index >= dda->point_count) {
    return false;
  }

  *frequency_hz = dda->current_hz;
  dda->index++;
  if (dda->index < dda->point_count) {
    dda->current_hz += dda->whole_step_hz;
    dda->error += dda->remainder_hz;
    if (dda->error >= dda->denominator) {
      dda->error -= dda->denominator;
      dda->current_hz++;
    }
  }
  return true;
}

zs407_db32_t zs407_db32_saturate(int32_t value)
{
  if (value > INT16_MAX) {
    return INT16_MAX;
  }
  if (value < (INT16_MIN + 1)) {
    return (INT16_MIN + 1);
  }
  return (zs407_db32_t)value;
}

zs407_core_status_t zs407_correction_cursor_init(
    zs407_correction_cursor_t *cursor,
    const zs407_correction_point_t *points, size_t count)
{
  if (cursor == NULL || points == NULL || count == 0U) {
    return ZS407_CORE_INVALID_ARGUMENT;
  }
  for (size_t i = 1U; i < count; ++i) {
    if (points[i - 1U].frequency_hz >= points[i].frequency_hz) {
      return ZS407_CORE_INVALID_ARGUMENT;
    }
  }
  cursor->points = points;
  cursor->count = count;
  cursor->segment = 0U;
  return ZS407_CORE_OK;
}

zs407_core_status_t zs407_correction_at(
    zs407_correction_cursor_t *cursor, uint64_t frequency_hz,
    zs407_db32_t *correction_db32)
{
  if (cursor == NULL || correction_db32 == NULL || cursor->points == NULL ||
      cursor->count == 0U) {
    return ZS407_CORE_INVALID_ARGUMENT;
  }

  const zs407_correction_point_t *points = cursor->points;
  if (frequency_hz <= points[0].frequency_hz || cursor->count == 1U) {
    cursor->segment = 0U;
    *correction_db32 = points[0].correction_db32;
    return ZS407_CORE_OK;
  }
  if (frequency_hz >= points[cursor->count - 1U].frequency_hz) {
    cursor->segment = cursor->count - 1U;
    *correction_db32 = points[cursor->count - 1U].correction_db32;
    return ZS407_CORE_OK;
  }

  if (cursor->segment >= cursor->count - 1U ||
      frequency_hz < points[cursor->segment].frequency_hz) {
    cursor->segment = 0U;
  }
  while (cursor->segment + 1U < cursor->count &&
         frequency_hz > points[cursor->segment + 1U].frequency_hz) {
    cursor->segment++;
  }

  const zs407_correction_point_t *a = &points[cursor->segment];
  const zs407_correction_point_t *b = &points[cursor->segment + 1U];
  uint64_t span = b->frequency_hz - a->frequency_hz;
  uint64_t offset = frequency_hz - a->frequency_hz;
  int32_t delta = (int32_t)b->correction_db32 - a->correction_db32;
  uint32_t magnitude = delta < 0 ? (uint32_t)(-(int64_t)delta)
                                 : (uint32_t)delta;
  if (magnitude != 0U &&
      offset > (uint64_t)INT64_MAX / (uint64_t)magnitude) {
    return ZS407_CORE_OUT_OF_RANGE;
  }
  int64_t numerator = (int64_t)delta * (int64_t)offset;
  int64_t rounded = numerator >= 0 ? (int64_t)(span / 2U)
                                   : -(int64_t)(span / 2U);
  int32_t value = (int32_t)a->correction_db32 +
                  (int32_t)((numerator + rounded) / (int64_t)span);
  *correction_db32 = zs407_db32_saturate(value);
  return ZS407_CORE_OK;
}

zs407_core_status_t zs407_quantile_db32(const zs407_db32_t *samples,
                                        size_t count, uint16_t quantile_q16,
                                        zs407_db32_t *scratch,
                                        size_t scratch_count,
                                        zs407_db32_t *result)
{
  if (samples == NULL || scratch == NULL || result == NULL || count == 0U) {
    return ZS407_CORE_INVALID_ARGUMENT;
  }
  if (scratch_count < count) {
    return ZS407_CORE_BUFFER_TOO_SMALL;
  }
  for (size_t i = 0U; i < count; ++i) {
    scratch[i] = samples[i];
  }
  for (size_t i = 1U; i < count; ++i) {
    zs407_db32_t value = scratch[i];
    size_t j = i;
    while (j > 0U && scratch[j - 1U] > value) {
      scratch[j] = scratch[j - 1U];
      --j;
    }
    scratch[j] = value;
  }
  uint64_t scaled = (uint64_t)quantile_q16 * (uint64_t)(count - 1U);
  size_t index = (size_t)((scaled + 32767U) / 65535U);
  *result = scratch[index];
  return ZS407_CORE_OK;
}

zs407_core_status_t zs407_parabolic_peak_offset_q15(
    zs407_db32_t left, zs407_db32_t center, zs407_db32_t right,
    int16_t *offset_q15)
{
  if (offset_q15 == NULL) {
    return ZS407_CORE_INVALID_ARGUMENT;
  }
  int32_t curvature = (int32_t)left - (2 * (int32_t)center) + right;
  if (curvature >= 0 || center < left || center < right) {
    *offset_q15 = 0;
    return ZS407_CORE_NOT_QUALIFIED;
  }
  int32_t numerator = ((int32_t)left - right) * 16384;
  int32_t offset = numerator / curvature;
  if (offset < -16384) {
    offset = -16384;
  } else if (offset > 16384) {
    offset = 16384;
  }
  *offset_q15 = (int16_t)offset;
  return ZS407_CORE_OK;
}
