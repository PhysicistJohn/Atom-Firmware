/* SPDX-License-Identifier: GPL-3.0-or-later */
#include "zs407_measurements.h"

#include <math.h>
#include <string.h>

#ifndef ZS407_EMBEDDED_MATH
#define ZS407_EMBEDDED_MATH 0
#endif

#if ZS407_EMBEDDED_MATH
typedef float measurement_real_t;
#define measurement_pow10(value) powf(10.0f, (value))
#define measurement_log10(value) log10f(value)
#else
typedef double measurement_real_t;
#define measurement_pow10(value) pow(10.0, (value))
#define measurement_log10(value) log10(value)
#endif

zs407_core_status_t zs407_db32_from_double(double db,
                                           zs407_db32_t *result)
{
  if (result == NULL || !isfinite(db)) {
    return ZS407_CORE_INVALID_ARGUMENT;
  }
  double scaled = db * (double)ZS407_TRACE_DB_SCALE;
  if (scaled >= 32767.0) {
    *result = 32767;
  } else if (scaled <= -32767.0) {
    *result = -32767;
  } else {
    scaled += scaled >= 0.0 ? 0.5 : -0.5;
    *result = (zs407_db32_t)scaled;
  }
  return ZS407_CORE_OK;
}

double zs407_db32_to_double(zs407_db32_t value)
{
  return (double)value / (double)ZS407_TRACE_DB_SCALE;
}

static measurement_real_t sample_milliwatts(zs407_db32_t sample)
{
  measurement_real_t dbm = (measurement_real_t)sample /
      (measurement_real_t)ZS407_TRACE_DB_SCALE;
  return measurement_pow10(dbm / (measurement_real_t)10.0);
}

zs407_core_status_t zs407_summarize_trace(
    const zs407_db32_t *samples, size_t count, uint32_t bin_width_hz,
    uint32_t enbw_hz, uint16_t occupied_basis_points,
    zs407_db32_t *scratch, size_t scratch_count,
    zs407_measurement_summary_t *summary)
{
  if (samples == NULL || scratch == NULL || summary == NULL || count == 0U ||
      count > UINT16_MAX || scratch_count < count || bin_width_hz == 0U ||
      enbw_hz == 0U || occupied_basis_points == 0U ||
      occupied_basis_points > 10000U) {
    return ZS407_CORE_INVALID_ARGUMENT;
  }

  memset(summary, 0, sizeof(*summary));
  summary->peak_db32 = -32767;
  summary->noise_db32 = ZS407_TRACE_INVALID_SAMPLE;
  summary->integrated_power_dbm32 = ZS407_TRACE_INVALID_SAMPLE;

  measurement_real_t total_mw = 0.0;
  size_t valid = 0U;
  for (size_t i = 0U; i < count; ++i) {
    if (samples[i] == ZS407_TRACE_INVALID_SAMPLE) {
      summary->flags |= ZS407_MEASUREMENT_HAS_GAPS;
      continue;
    }
    scratch[valid++] = samples[i];
    total_mw += sample_milliwatts(samples[i]);
    if (valid == 1U || samples[i] > summary->peak_db32) {
      summary->peak_db32 = samples[i];
      summary->peak_index = (uint16_t)i;
    }
  }
  if (valid == 0U || total_mw <= 0.0 || !isfinite(total_mw)) {
    return ZS407_CORE_NOT_QUALIFIED;
  }
  summary->valid_points = (uint16_t)valid;

  zs407_db32_t noise = 0;
  if (zs407_quantile_db32(scratch, valid, 13107U, scratch, scratch_count,
                          &noise) == ZS407_CORE_OK) {
    summary->noise_db32 = noise;
    summary->flags |= ZS407_MEASUREMENT_NOISE_VALID;
  }

  measurement_real_t integrated_mw = total_mw *
      (measurement_real_t)bin_width_hz / (measurement_real_t)enbw_hz;
  if (integrated_mw > 0.0 && isfinite(integrated_mw) &&
      zs407_db32_from_double(10.0 * measurement_log10(integrated_mw),
                             &summary->integrated_power_dbm32) ==
          ZS407_CORE_OK) {
    summary->flags |= ZS407_MEASUREMENT_POWER_VALID;
  }

  measurement_real_t tail_fraction =
      (measurement_real_t)(10000U - occupied_basis_points) /
      (measurement_real_t)20000.0;
  measurement_real_t lower_target = total_mw * tail_fraction;
  measurement_real_t upper_target =
      total_mw * ((measurement_real_t)1.0 - tail_fraction);
  measurement_real_t cumulative = 0.0;
  bool lower_found = false;
  for (size_t i = 0U; i < count; ++i) {
    if (samples[i] != ZS407_TRACE_INVALID_SAMPLE) {
      cumulative += sample_milliwatts(samples[i]);
    }
    if (!lower_found && cumulative >= lower_target) {
      summary->occupied_start_index = (uint16_t)i;
      lower_found = true;
    }
    if (cumulative >= upper_target) {
      summary->occupied_stop_index = (uint16_t)i;
      summary->flags |= ZS407_MEASUREMENT_OBW_VALID;
      break;
    }
  }

  if (summary->peak_index > 0U && summary->peak_index + 1U < count &&
      samples[summary->peak_index - 1U] != ZS407_TRACE_INVALID_SAMPLE &&
      samples[summary->peak_index + 1U] != ZS407_TRACE_INVALID_SAMPLE &&
      zs407_parabolic_peak_offset_q15(
          samples[summary->peak_index - 1U], summary->peak_db32,
          samples[summary->peak_index + 1U],
          &summary->peak_offset_q15) == ZS407_CORE_OK) {
    summary->flags |= ZS407_MEASUREMENT_PEAK_INTERPOLATED;
  }
  return ZS407_CORE_OK;
}
