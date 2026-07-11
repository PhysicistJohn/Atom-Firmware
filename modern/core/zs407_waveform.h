/* SPDX-License-Identifier: GPL-3.0-or-later */
#ifndef ZS407_WAVEFORM_H
#define ZS407_WAVEFORM_H

#include "zs407_core.h"

typedef enum {
  ZS407_WAVE_SINE = 0,
  ZS407_WAVE_TRIANGLE = 1,
  ZS407_WAVE_SQUARE = 2,
  ZS407_WAVE_NOISE = 3
} zs407_wave_shape_t;

typedef struct {
  uint32_t phase;
  uint32_t noise_state;
} zs407_wave_oscillator_t;

typedef struct {
  uint16_t prescaler;
  uint16_t auto_reload;
  uint32_t actual_rate_hz;
} zs407_timer16_plan_t;

zs407_core_status_t zs407_timer16_plan(uint32_t timer_clock_hz,
                                       uint32_t requested_rate_hz,
                                       zs407_timer16_plan_t *plan);

int16_t zs407_sine_q15(uint32_t phase);
zs407_core_status_t zs407_render_dac12(
    zs407_wave_shape_t shape, uint32_t frequency_millihz,
    uint32_t sample_rate_hz, uint16_t amplitude, uint16_t offset,
    zs407_wave_oscillator_t *oscillator, uint16_t *output,
    size_t sample_count, uint32_t *actual_frequency_millihz);

typedef enum {
  ZS407_EVENT_GATE = 0,
  ZS407_EVENT_SET_FREQUENCY_HZ = 1,
  ZS407_EVENT_SET_LEVEL_DBM_X10 = 2,
  ZS407_EVENT_DAC_SAMPLE = 3,
  ZS407_EVENT_WAIT_TRIGGER = 4,
  ZS407_EVENT_END = 5
} zs407_wave_event_opcode_t;

typedef struct {
  uint32_t at_us;
  uint8_t opcode;
  uint8_t flags;
  uint16_t reserved;
  int64_t value;
} zs407_wave_event_t;

typedef struct {
  uint32_t duration_us;
  uint64_t maximum_frequency_hz;
  int16_t minimum_level_dbm_x10;
  int16_t maximum_level_dbm_x10;
  uint16_t event_count;
  uint16_t gate_transitions;
} zs407_wave_program_report_t;

zs407_core_status_t zs407_validate_wave_program(
    const zs407_wave_event_t *events, size_t event_count,
    zs407_wave_program_report_t *report);

typedef enum {
  ZS407_RF_MOD_OOK = 0,
  ZS407_RF_MOD_2FSK = 1,
  ZS407_RF_MOD_2GFSK = 2,
  ZS407_RF_MOD_4FSK = 3,
  ZS407_RF_MOD_4GFSK = 4,
  ZS407_RF_MOD_PRBS = 5
} zs407_rf_modulation_t;

typedef struct {
  uint32_t bit_rate;
  uint32_t deviation_hz;
  uint16_t payload_bytes;
  uint8_t modulation;
  uint8_t bits_per_symbol;
  uint32_t symbol_rate;
} zs407_rf_fifo_plan_t;

zs407_core_status_t zs407_rf_fifo_plan(zs407_rf_modulation_t modulation,
                                       uint32_t bit_rate,
                                       uint32_t deviation_hz,
                                       size_t payload_bytes,
                                       zs407_rf_fifo_plan_t *plan);

zs407_core_status_t zs407_quantize_pe4302_db32(
    zs407_db32_t requested_attenuation, uint8_t *code,
    zs407_db32_t *actual_attenuation);

#endif /* ZS407_WAVEFORM_H */
