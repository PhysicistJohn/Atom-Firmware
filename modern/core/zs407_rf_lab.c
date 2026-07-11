/* SPDX-License-Identifier: GPL-3.0-or-later */
#include "zs407_rf_lab.h"

#include <limits.h>
#include <string.h>

#define SI4468_MODULUS UINT64_C(524288)
#define ZS407_REFERENCE_SCALE UINT64_C(100)

zs407_core_status_t zs407_si4468_hop_plan(
    uint64_t frequency_hz, uint64_t reference_hz_x100,
    zs407_si4468_hop_plan_t *plan)
{
  if (plan == NULL || reference_hz_x100 == 0U) {
    return ZS407_CORE_INVALID_ARGUMENT;
  }
  memset(plan, 0, sizeof(*plan));
  plan->requested_hz = frequency_hz;

  uint32_t divider = 0U;
  if (frequency_hz >= 822000000U && frequency_hz <= 1150000000U) {
    plan->band = 0U;
    divider = 4U;
  } else if (frequency_hz >= 411000000U && frequency_hz <= 566000000U) {
    plan->band = 2U;
    divider = 8U;
  } else if (frequency_hz >= 329000000U && frequency_hz <= 454000000U) {
    plan->band = 1U;
    divider = 10U;
  } else if (frequency_hz >= 274000000U && frequency_hz <= 378000000U) {
    plan->band = 3U;
    divider = 12U;
  } else if (frequency_hz >= 137000000U && frequency_hz <= 189000000U) {
    plan->band = 5U;
    divider = 24U;
  } else {
    return ZS407_CORE_OUT_OF_RANGE;
  }

  uint64_t scaled_divider = divider * ZS407_REFERENCE_SCALE;
  uint64_t denominator = 2U * reference_hz_x100;
  if (frequency_hz > UINT64_MAX / scaled_divider) {
    return ZS407_CORE_OUT_OF_RANGE;
  }
  uint64_t numerator = frequency_hz * scaled_divider;
  uint64_t ratio = numerator / denominator;
  if (ratio == 0U || ratio - 1U > UINT8_MAX ||
      numerator > UINT64_MAX / SI4468_MODULUS) {
    return ZS407_CORE_OUT_OF_RANGE;
  }
  uint64_t integer = ratio - 1U;
  uint64_t fraction = (numerator * SI4468_MODULUS) / denominator -
                      integer * SI4468_MODULUS;
  if (fraction > UINT32_MAX) {
    return ZS407_CORE_OUT_OF_RANGE;
  }

  plan->integer = (uint8_t)integer;
  plan->fraction = (uint32_t)fraction;
  plan->divider = (uint8_t)divider;
  plan->actual_hz =
      (integer * SI4468_MODULUS + fraction) * denominator /
      scaled_divider / SI4468_MODULUS;

  /* Normalized form of the disabled source estimate; hardware must qualify it. */
  int64_t vco_hz = (int64_t)(frequency_hz / 4U) * divider;
  int64_t vco = INT64_C(2091) +
      (((vco_hz - INT64_C(850000000)) / 1000) * 492) / 200000;
  if (vco >= 0 && vco <= UINT16_MAX) {
    plan->vco_count_estimate = (uint16_t)vco;
    plan->vco_estimate_in_range = true;
  }
  return ZS407_CORE_OK;
}

zs407_core_status_t zs407_max2871_plan(
    uint64_t frequency_hz, uint64_t pfd_hz_x100, uint16_t modulus,
    zs407_max2871_plan_t *plan)
{
  if (plan == NULL || pfd_hz_x100 == 0U || modulus < 2U) {
    return ZS407_CORE_INVALID_ARGUMENT;
  }
  memset(plan, 0, sizeof(*plan));
  plan->requested_hz = frequency_hz;
  plan->modulus = modulus;

  uint32_t divider;
  if (frequency_hz >= 3000000000U) {
    divider = 1U;
    plan->divider_code = 0U;
  } else if (frequency_hz >= 1500000000U) {
    divider = 2U;
    plan->divider_code = 1U;
  } else if (frequency_hz >= 750000000U) {
    divider = 4U;
    plan->divider_code = 2U;
  } else if (frequency_hz >= 375000000U) {
    divider = 8U;
    plan->divider_code = 3U;
  } else if (frequency_hz >= 187500000U) {
    divider = 16U;
    plan->divider_code = 4U;
  } else if (frequency_hz >= 137500000U) {
    divider = 32U;
    plan->divider_code = 5U;
  } else if (frequency_hz >= 68750000U) {
    divider = 64U;
    plan->divider_code = 6U;
  } else if (frequency_hz >= 34375000U) {
    divider = 128U;
    plan->divider_code = 7U;
  } else {
    return ZS407_CORE_OUT_OF_RANGE;
  }

  uint64_t scaled_divider = divider * ZS407_REFERENCE_SCALE;
  uint64_t modulus_x2 = (uint64_t)modulus * 2U;
  if (frequency_hz > UINT64_MAX / scaled_divider ||
      frequency_hz * scaled_divider > UINT64_MAX / modulus_x2) {
    return ZS407_CORE_OUT_OF_RANGE;
  }
  uint64_t combined =
      (frequency_hz * scaled_divider * modulus_x2) / pfd_hz_x100 + 1U;
  uint64_t integer = combined / modulus_x2;
  uint64_t fraction = (combined - integer * modulus_x2) >> 1;
  if (fraction >= modulus) {
    fraction -= modulus;
    integer++;
  }
  if (integer > UINT16_MAX || fraction > UINT16_MAX) {
    return ZS407_CORE_OUT_OF_RANGE;
  }

  plan->integer = (uint16_t)integer;
  plan->fraction = (uint16_t)fraction;
  plan->divider = (uint8_t)divider;
  plan->actual_hz =
      (pfd_hz_x100 * (integer * modulus + fraction)) /
      scaled_divider / modulus;
  plan->register0 = ((uint32_t)plan->integer << 15) |
                    ((uint32_t)plan->fraction << 3);
  plan->register1 = ((uint32_t)modulus << 3) | UINT32_C(1) |
                    (UINT32_C(1) << 15) | (UINT32_C(1) << 27);
  return ZS407_CORE_OK;
}

zs407_core_status_t zs407_select_refinement_windows(
    const zs407_db32_t *samples, size_t count, zs407_db32_t noise_floor,
    zs407_db32_t minimum_prominence, uint16_t radius,
    zs407_refinement_window_t *windows, size_t window_capacity,
    size_t *window_count)
{
  if (samples == NULL || windows == NULL || window_count == NULL || count < 3U ||
      count > UINT16_MAX || window_capacity == 0U ||
      minimum_prominence < 0) {
    return ZS407_CORE_INVALID_ARGUMENT;
  }
  *window_count = 0U;
  int32_t threshold = (int32_t)noise_floor + minimum_prominence;
  for (size_t index = 1U; index + 1U < count; ++index) {
    if (samples[index] == ZS407_TRACE_INVALID_SAMPLE ||
        samples[index] < threshold || samples[index] < samples[index - 1U] ||
        samples[index] < samples[index + 1U]) {
      continue;
    }
    size_t first = index > radius ? index - radius : 0U;
    size_t last = index + radius;
    if (last >= count) {
      last = count - 1U;
    }
    if (*window_count > 0U &&
        first <= windows[*window_count - 1U].last_index + 1U) {
      zs407_refinement_window_t *window = &windows[*window_count - 1U];
      if (last > window->last_index) {
        window->last_index = (uint16_t)last;
      }
      if (samples[index] > samples[window->peak_index]) {
        window->peak_index = (uint16_t)index;
      }
      continue;
    }
    if (*window_count >= window_capacity) {
      return ZS407_CORE_BUFFER_TOO_SMALL;
    }
    windows[*window_count].first_index = (uint16_t)first;
    windows[*window_count].last_index = (uint16_t)last;
    windows[*window_count].peak_index = (uint16_t)index;
    (*window_count)++;
  }
  return ZS407_CORE_OK;
}
