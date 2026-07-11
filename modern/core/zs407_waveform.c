/* SPDX-License-Identifier: GPL-3.0-or-later */
#include "zs407_waveform.h"

#include "../generated/zs407_sine_q15.h"

#include <limits.h>
#include <string.h>

_Static_assert(sizeof(zs407_wave_event_t) == 16U,
               "wave event wire/storage layout must remain 16 bytes");

zs407_core_status_t zs407_timer16_plan(uint32_t timer_clock_hz,
                                       uint32_t requested_rate_hz,
                                       zs407_timer16_plan_t *plan)
{
  if (plan == NULL || timer_clock_hz == 0U || requested_rate_hz == 0U ||
      requested_rate_hz > timer_clock_hz) {
    return ZS407_CORE_INVALID_ARGUMENT;
  }

  uint64_t full_scale = (uint64_t)requested_rate_hz * UINT64_C(65536);
  uint32_t prescaler_divisor =
      (uint32_t)(((uint64_t)timer_clock_hz + full_scale - 1U) / full_scale);
  if (prescaler_divisor == 0U) {
    prescaler_divisor = 1U;
  }
  if (prescaler_divisor > 65536U) {
    return ZS407_CORE_OUT_OF_RANGE;
  }

  uint64_t period_denominator =
      (uint64_t)prescaler_divisor * requested_rate_hz;
  uint32_t period = (uint32_t)(((uint64_t)timer_clock_hz +
                                period_denominator / 2U) /
                               period_denominator);
  if (period == 0U) {
    period = 1U;
  } else if (period > 65536U) {
    period = 65536U;
  }

  uint64_t total_divisor = (uint64_t)prescaler_divisor * period;
  plan->prescaler = (uint16_t)(prescaler_divisor - 1U);
  plan->auto_reload = (uint16_t)(period - 1U);
  plan->actual_rate_hz = (uint32_t)(((uint64_t)timer_clock_hz +
                                    total_divisor / 2U) /
                                   total_divisor);
  return ZS407_CORE_OK;
}

int16_t zs407_sine_q15(uint32_t phase)
{
  uint8_t position = (uint8_t)(phase >> 24);
  uint8_t quadrant = position >> 6;
  uint8_t index = position & 63U;
  switch (quadrant) {
  case 0U:
    return zs407_sine_quarter_q15[index];
  case 1U:
    return zs407_sine_quarter_q15[64U - index];
  case 2U:
    return (int16_t)-zs407_sine_quarter_q15[index];
  default:
    return (int16_t)-zs407_sine_quarter_q15[64U - index];
  }
}

static int16_t triangle_q15(uint32_t phase)
{
  uint32_t position = phase >> 16;
  int32_t value = position < 32768U
                      ? -32768 + (int32_t)(position * 2U)
                      : 98303 - (int32_t)(position * 2U);
  return (int16_t)value;
}

static uint32_t xorshift32(uint32_t *state)
{
  uint32_t value = *state == 0U ? UINT32_C(0x4075a17e) : *state;
  value ^= value << 13;
  value ^= value >> 17;
  value ^= value << 5;
  *state = value;
  return value;
}

zs407_core_status_t zs407_render_dac12(
    zs407_wave_shape_t shape, uint32_t frequency_millihz,
    uint32_t sample_rate_hz, uint16_t amplitude, uint16_t offset,
    zs407_wave_oscillator_t *oscillator, uint16_t *output,
    size_t sample_count, uint32_t *actual_frequency_millihz)
{
  if (oscillator == NULL || output == NULL || actual_frequency_millihz == NULL ||
      sample_count == 0U || sample_rate_hz == 0U || sample_rate_hz > 200000U ||
      amplitude > 4095U || offset > 4095U || shape > ZS407_WAVE_NOISE) {
    return ZS407_CORE_INVALID_ARGUMENT;
  }

  uint32_t phase_increment = 0U;
  if (shape != ZS407_WAVE_NOISE) {
    uint64_t denominator = (uint64_t)sample_rate_hz * 1000U;
    uint64_t numerator = (uint64_t)frequency_millihz << 32;
    uint64_t increment = (numerator + denominator / 2U) / denominator;
    if (increment == 0U || increment > UINT32_C(0x80000000)) {
      return ZS407_CORE_OUT_OF_RANGE;
    }
    phase_increment = (uint32_t)increment;
    *actual_frequency_millihz = (uint32_t)(
        ((uint64_t)phase_increment * denominator + UINT64_C(0x80000000)) >>
        32);
  } else {
    *actual_frequency_millihz = 0U;
  }

  for (size_t i = 0U; i < sample_count; ++i) {
    int16_t normalized;
    switch (shape) {
    case ZS407_WAVE_SINE:
      normalized = zs407_sine_q15(oscillator->phase);
      break;
    case ZS407_WAVE_TRIANGLE:
      normalized = triangle_q15(oscillator->phase);
      break;
    case ZS407_WAVE_SQUARE:
      normalized = (oscillator->phase & UINT32_C(0x80000000)) != 0U
                       ? -32768
                       : 32767;
      break;
    default:
      normalized = (int16_t)((int32_t)
          (xorshift32(&oscillator->noise_state) >> 16) - 32768);
      break;
    }
    int32_t value = (int32_t)offset +
                    ((int32_t)amplitude * normalized) / 32768;
    if (value < 0) {
      value = 0;
    } else if (value > 4095) {
      value = 4095;
    }
    output[i] = (uint16_t)value;
    oscillator->phase += phase_increment;
  }
  return ZS407_CORE_OK;
}

zs407_core_status_t zs407_validate_wave_program(
    const zs407_wave_event_t *events, size_t event_count,
    zs407_wave_program_report_t *report)
{
  if (events == NULL || report == NULL || event_count < 2U ||
      event_count > UINT16_MAX) {
    return ZS407_CORE_INVALID_ARGUMENT;
  }
  memset(report, 0, sizeof(*report));
  report->event_count = (uint16_t)event_count;
  report->minimum_level_dbm_x10 = INT16_MAX;
  report->maximum_level_dbm_x10 = INT16_MIN;
  bool gate_on = false;
  if (events[0].at_us != 0U || events[0].opcode != ZS407_EVENT_GATE ||
      events[0].value != 0) {
    return ZS407_CORE_NOT_QUALIFIED;
  }

  for (size_t i = 0U; i < event_count; ++i) {
    if ((i > 0U && events[i].at_us < events[i - 1U].at_us) ||
        events[i].reserved != 0U || events[i].flags != 0U ||
        events[i].opcode > ZS407_EVENT_END) {
      return ZS407_CORE_INVALID_ARGUMENT;
    }
    switch ((zs407_wave_event_opcode_t)events[i].opcode) {
    case ZS407_EVENT_GATE:
      if (events[i].value != 0 && events[i].value != 1) {
        return ZS407_CORE_INVALID_ARGUMENT;
      }
      if (gate_on != (events[i].value != 0)) {
        report->gate_transitions++;
      }
      gate_on = events[i].value != 0;
      break;
    case ZS407_EVENT_SET_FREQUENCY_HZ:
      if (events[i].value < 0 || events[i].value > INT64_C(12000000000)) {
        return ZS407_CORE_OUT_OF_RANGE;
      }
      if ((uint64_t)events[i].value > report->maximum_frequency_hz) {
        report->maximum_frequency_hz = (uint64_t)events[i].value;
      }
      break;
    case ZS407_EVENT_SET_LEVEL_DBM_X10:
      if (events[i].value < -1200 || events[i].value > 100) {
        return ZS407_CORE_OUT_OF_RANGE;
      }
      if (events[i].value < report->minimum_level_dbm_x10) {
        report->minimum_level_dbm_x10 = (int16_t)events[i].value;
      }
      if (events[i].value > report->maximum_level_dbm_x10) {
        report->maximum_level_dbm_x10 = (int16_t)events[i].value;
      }
      break;
    case ZS407_EVENT_DAC_SAMPLE:
      if (events[i].value < 0 || events[i].value > 4095) {
        return ZS407_CORE_OUT_OF_RANGE;
      }
      break;
    case ZS407_EVENT_WAIT_TRIGGER:
      if (gate_on) {
        return ZS407_CORE_NOT_QUALIFIED;
      }
      break;
    case ZS407_EVENT_END:
      if (i + 1U != event_count || gate_on || events[i].value != 0) {
        return ZS407_CORE_NOT_QUALIFIED;
      }
      break;
    }
  }
  if (events[event_count - 1U].opcode != ZS407_EVENT_END || gate_on) {
    return ZS407_CORE_NOT_QUALIFIED;
  }
  report->duration_us = events[event_count - 1U].at_us;
  if (report->minimum_level_dbm_x10 == INT16_MAX) {
    report->minimum_level_dbm_x10 = 0;
    report->maximum_level_dbm_x10 = 0;
  }
  return ZS407_CORE_OK;
}

zs407_core_status_t zs407_rf_fifo_plan(zs407_rf_modulation_t modulation,
                                       uint32_t bit_rate,
                                       uint32_t deviation_hz,
                                       size_t payload_bytes,
                                       zs407_rf_fifo_plan_t *plan)
{
  if (plan == NULL || modulation > ZS407_RF_MOD_PRBS || bit_rate < 100U ||
      bit_rate > 1000000U || payload_bytes == 0U || payload_bytes > 64U) {
    return ZS407_CORE_INVALID_ARGUMENT;
  }
  bool is_ook = modulation == ZS407_RF_MOD_OOK;
  bool is_four_level = modulation == ZS407_RF_MOD_4FSK ||
                       modulation == ZS407_RF_MOD_4GFSK;
  if (!is_ook && deviation_hz == 0U) {
    return ZS407_CORE_INVALID_ARGUMENT;
  }
  if (deviation_hz > 500000U) {
    return ZS407_CORE_OUT_OF_RANGE;
  }
  plan->bit_rate = bit_rate;
  plan->deviation_hz = deviation_hz;
  plan->payload_bytes = (uint16_t)payload_bytes;
  plan->modulation = (uint8_t)modulation;
  plan->bits_per_symbol = is_four_level ? 2U : 1U;
  plan->symbol_rate = bit_rate / plan->bits_per_symbol;
  return ZS407_CORE_OK;
}

zs407_core_status_t zs407_quantize_pe4302_db32(
    zs407_db32_t requested_attenuation, uint8_t *code,
    zs407_db32_t *actual_attenuation)
{
  if (code == NULL || actual_attenuation == NULL ||
      requested_attenuation < 0 || requested_attenuation > (63 * 16)) {
    return ZS407_CORE_OUT_OF_RANGE;
  }
  uint16_t rounded = (uint16_t)requested_attenuation + 8U;
  *code = (uint8_t)(rounded / 16U);
  if (*code > 63U) {
    *code = 63U;
  }
  *actual_attenuation = (zs407_db32_t)(*code * 16U);
  return ZS407_CORE_OK;
}
