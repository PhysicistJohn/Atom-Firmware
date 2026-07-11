/* SPDX-License-Identifier: GPL-3.0-or-later */
#include "modern/core/zs407_core.h"
#include "modern/core/zs407_fft.h"
#include "modern/core/zs407_measurements.h"
#include "modern/core/zs407_protocol.h"
#include "modern/core/zs407_rf_lab.h"
#include "modern/core/zs407_services.h"
#include "modern/core/zs407_ui_model.h"
#include "modern/core/zs407_waveform.h"

#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define CHECK(condition)                                                       \
  do {                                                                         \
    if (!(condition)) {                                                        \
      fprintf(stderr, "CHECK failed at %s:%d: %s\n", __FILE__, __LINE__,      \
              #condition);                                                     \
      return 1;                                                                \
    }                                                                          \
  } while (0)

static int test_contract(void)
{
  CHECK(ZS407_SCHEMA_VERSION == 1U);
  CHECK(ZS407_PROTOCOL_MAGIC == 0x5a53U);
  CHECK(ZS407_TRACE_DB_SCALE == 32U);
  CHECK(ZS407_TRACE_INVALID_SAMPLE == -32768);
  return 0;
}

static int test_frequency_dda(void)
{
  const zs407_sweep_request_t request = {1000000000U, 1000000010U, 4U};
  const uint64_t expected[] = {1000000000U, 1000000003U,
                               1000000007U, 1000000010U};
  zs407_frequency_dda_t dda;
  CHECK(zs407_frequency_dda_init(&dda, &request) == ZS407_CORE_OK);
  for (size_t i = 0U; i < 4U; ++i) {
    uint64_t actual = 0U;
    CHECK(zs407_frequency_dda_next(&dda, &actual));
    CHECK(actual == expected[i]);
  }
  uint64_t unused = 0U;
  CHECK(!zs407_frequency_dda_next(&dda, &unused));

  const zs407_sweep_request_t one = {UINT64_C(12345678901),
                                     UINT64_C(12345678901), 1U};
  CHECK(zs407_frequency_dda_init(&dda, &one) == ZS407_CORE_OK);
  CHECK(zs407_frequency_dda_next(&dda, &unused));
  CHECK(unused == one.start_hz);

  const zs407_sweep_request_t backwards = {2U, 1U, 2U};
  CHECK(zs407_frequency_dda_init(&dda, &backwards) ==
        ZS407_CORE_INVALID_ARGUMENT);

  /* Exhaustively compare the streaming form with the stock rational formula. */
  for (uint16_t points = 2U; points < 512U; ++points) {
    zs407_sweep_request_t grid = {UINT64_C(123456789),
                                  UINT64_C(123456789) + 1000003U, points};
    CHECK(zs407_frequency_dda_init(&dda, &grid) == ZS407_CORE_OK);
    uint64_t span = grid.stop_hz - grid.start_hz;
    uint64_t whole = span / (points - 1U);
    uint64_t remainder = span % (points - 1U);
    for (uint16_t index = 0U; index < points; ++index) {
      uint64_t actual = 0U;
      uint64_t reference = grid.start_hz + whole * index +
          (((points - 1U) / 2U) + remainder * index) / (points - 1U);
      CHECK(zs407_frequency_dda_next(&dda, &actual));
      CHECK(actual == reference);
    }
  }
  return 0;
}

static int test_fixed_point_and_correction(void)
{
  CHECK(zs407_db32_saturate(50000) == 32767);
  CHECK(zs407_db32_saturate(-50000) == -32767);
  CHECK(zs407_db32_saturate(-1234) == -1234);

  const zs407_correction_point_t points[] = {
      {100U, -320}, {200U, 0}, {400U, 640}};
  zs407_correction_cursor_t cursor;
  zs407_db32_t result = 0;
  CHECK(zs407_correction_cursor_init(&cursor, points, 3U) == ZS407_CORE_OK);
  CHECK(zs407_correction_at(&cursor, 150U, &result) == ZS407_CORE_OK);
  CHECK(result == -160);
  CHECK(zs407_correction_at(&cursor, 300U, &result) == ZS407_CORE_OK);
  CHECK(result == 320);
  CHECK(zs407_correction_at(&cursor, 125U, &result) == ZS407_CORE_OK);
  CHECK(result == -240);
  CHECK(zs407_correction_at(&cursor, 999U, &result) == ZS407_CORE_OK);
  CHECK(result == 640);

  const zs407_correction_point_t invalid[] = {{100U, 0}, {100U, 1}};
  CHECK(zs407_correction_cursor_init(&cursor, invalid, 2U) ==
        ZS407_CORE_INVALID_ARGUMENT);

  const zs407_correction_point_t extreme[] = {
      {0U, -32767}, {UINT64_MAX, 32767}};
  CHECK(zs407_correction_cursor_init(&cursor, extreme, 2U) == ZS407_CORE_OK);
  CHECK(zs407_correction_at(&cursor, UINT64_MAX / 2U, &result) ==
        ZS407_CORE_OUT_OF_RANGE);
  return 0;
}

static int test_statistics(void)
{
  const zs407_db32_t values[] = {-3200, -3000, -1000, -3100, -3050};
  zs407_db32_t scratch[5];
  zs407_db32_t result = 0;
  CHECK(zs407_quantile_db32(values, 5U, 32768U, scratch, 5U, &result) ==
        ZS407_CORE_OK);
  CHECK(result == -3050);
  CHECK(zs407_quantile_db32(values, 5U, 0U, scratch, 5U, &result) ==
        ZS407_CORE_OK);
  CHECK(result == -3200);
  CHECK(zs407_quantile_db32(values, 5U, 65535U, scratch, 4U, &result) ==
        ZS407_CORE_BUFFER_TOO_SMALL);

  int16_t offset = 123;
  CHECK(zs407_parabolic_peak_offset_q15(-100, 0, -100, &offset) ==
        ZS407_CORE_OK);
  CHECK(offset == 0);
  CHECK(zs407_parabolic_peak_offset_q15(-100, 0, -200, &offset) ==
        ZS407_CORE_OK);
  CHECK(offset < 0);
  CHECK(zs407_parabolic_peak_offset_q15(1, 0, 1, &offset) ==
        ZS407_CORE_NOT_QUALIFIED);
  return 0;
}

static size_t read_hex_fixture(const char *path, uint8_t *output,
                               size_t capacity)
{
  FILE *stream = fopen(path, "r");
  if (stream == NULL) {
    return 0U;
  }
  size_t count = 0U;
  char line[256];
  while (fgets(line, sizeof(line), stream) != NULL) {
    char *cursor = line;
    while (*cursor != '\0' && *cursor != '#') {
      unsigned value = 0U;
      int consumed = 0;
      if (sscanf(cursor, " %2x%n", &value, &consumed) == 1) {
        if (count >= capacity) {
          fclose(stream);
          return 0U;
        }
        output[count++] = (uint8_t)value;
        cursor += consumed;
      } else {
        ++cursor;
      }
    }
  }
  fclose(stream);
  return count;
}

static uint32_t prng_state = UINT32_C(0x40740701);

static uint32_t next_random(void)
{
  prng_state ^= prng_state << 13;
  prng_state ^= prng_state >> 17;
  prng_state ^= prng_state << 5;
  return prng_state;
}

static int test_protocol(const char *fixture_path)
{
  static const uint8_t digits[] = "123456789";
  CHECK(zs407_crc32(digits, sizeof(digits) - 1U) == UINT32_C(0xcbf43926));

  uint8_t fixture[64];
  size_t fixture_length = read_hex_fixture(fixture_path, fixture,
                                           sizeof(fixture));
  CHECK(fixture_length == 18U);
  zs407_frame_t decoded;
  CHECK(zs407_frame_decode(fixture, fixture_length, &decoded) ==
        ZS407_CORE_OK);
  CHECK(decoded.flags == 0xa5U);
  CHECK(decoded.request_id == 0x1234U);
  CHECK(decoded.command == ZS407_COMMAND_CAPABILITIES);
  CHECK(decoded.payload_length == 4U);
  CHECK(memcmp(decoded.payload, "\xde\xad\xbe\xef", 4U) == 0);

  uint8_t encoded[96];
  size_t encoded_length = 0U;
  CHECK(zs407_frame_encode(&decoded, encoded, sizeof(encoded),
                           &encoded_length) == ZS407_CORE_OK);
  CHECK(encoded_length == fixture_length);
  CHECK(memcmp(encoded, fixture, fixture_length) == 0);
  encoded[10] ^= 1U;
  CHECK(zs407_frame_decode(encoded, encoded_length, &decoded) ==
        ZS407_CORE_BAD_FRAME);

  for (unsigned iteration = 0U; iteration < 10000U; ++iteration) {
    uint8_t payload[64];
    uint16_t payload_length = (uint16_t)(next_random() % sizeof(payload));
    for (uint16_t i = 0U; i < payload_length; ++i) {
      payload[i] = (uint8_t)next_random();
    }
    zs407_frame_t input = {(uint8_t)next_random(), (uint16_t)next_random(),
                           (uint16_t)next_random(), payload, payload_length};
    CHECK(zs407_frame_encode(&input, encoded, sizeof(encoded),
                             &encoded_length) == ZS407_CORE_OK);
    CHECK(zs407_frame_decode(encoded, encoded_length, &decoded) ==
          ZS407_CORE_OK);
    CHECK(decoded.flags == input.flags);
    CHECK(decoded.request_id == input.request_id);
    CHECK(decoded.command == input.command);
    CHECK(decoded.payload_length == input.payload_length);
    CHECK(memcmp(decoded.payload, input.payload, input.payload_length) == 0);
  }
  return 0;
}

static int test_services(void)
{
  zs407_hardware_caps_t caps;
  CHECK(zs407_hardware_caps(103U, &caps));
  CHECK(caps.hardware_id == 103U);
  CHECK(caps.first_if_hz == 1070100000U);
  CHECK(caps.normal_input_max_hz == 900000000U);
  CHECK(caps.synthesized_limit_hz == UINT64_C(7370100000));
  CHECK(caps.has_plus_if && caps.has_max2871);
  CHECK(!zs407_hardware_caps(999U, &caps));
  CHECK(caps.hardware_id == 999U);
  CHECK(!caps.has_max2871);

  zs407_rf_state_t previous = {433000000U, 1503000000U, 0, -100, 3U,
                               ZS407_RF_PATH_LOW, false};
  zs407_rf_state_t next = previous;
  CHECK(zs407_rf_state_diff(&previous, &next) == 0U);
  next.local_oscillator_hz++;
  next.attenuation_db_x2 = 10;
  uint32_t dirty = zs407_rf_state_diff(&previous, &next);
  CHECK(dirty == (ZS407_RF_DIRTY_LOCAL_OSCILLATOR |
                  ZS407_RF_DIRTY_ATTENUATOR));
  CHECK(zs407_rf_settle_class(dirty) == ZS407_SETTLE_SYNTHESIZER);
  CHECK(zs407_rf_state_diff(NULL, &next) == ZS407_RF_DIRTY_ALL);

  zs407_bus_scheduler_t scheduler;
  zs407_bus_scheduler_init(&scheduler);
  CHECK(zs407_bus_request(&scheduler, ZS407_BUS_STORAGE) == ZS407_CORE_OK);
  CHECK(zs407_bus_request(&scheduler, ZS407_BUS_DISPLAY) == ZS407_CORE_OK);
  CHECK(zs407_bus_request(&scheduler, ZS407_BUS_RF) == ZS407_CORE_OK);
  CHECK(zs407_bus_grant_next(&scheduler) == ZS407_BUS_RF);
  CHECK(zs407_bus_grant_next(&scheduler) == ZS407_BUS_NONE);
  CHECK(zs407_bus_release(&scheduler, ZS407_BUS_DISPLAY) ==
        ZS407_CORE_INVALID_ARGUMENT);
  CHECK(zs407_bus_release(&scheduler, ZS407_BUS_RF) == ZS407_CORE_OK);
  CHECK(zs407_bus_grant_next(&scheduler) == ZS407_BUS_DISPLAY);
  CHECK(zs407_bus_release(&scheduler, ZS407_BUS_DISPLAY) == ZS407_CORE_OK);
  CHECK(zs407_bus_grant_next(&scheduler) == ZS407_BUS_STORAGE);

  zs407_profile_stats_t stats;
  zs407_profile_reset(&stats);
  CHECK(zs407_profile_mean(&stats) == 0U);
  zs407_profile_observe(&stats, 100U);
  zs407_profile_observe(&stats, 50U);
  zs407_profile_observe(&stats, 150U);
  CHECK(stats.minimum_cycles == 50U);
  CHECK(stats.maximum_cycles == 150U);
  CHECK(zs407_profile_mean(&stats) == 100U);
  CHECK(zs407_services_selftest() == 0U);
  return 0;
}

static int test_measurements(void)
{
  zs407_db32_t converted = 0;
  CHECK(zs407_db32_from_double(-10.25, &converted) == ZS407_CORE_OK);
  CHECK(converted == -328);
  CHECK(zs407_db32_to_double(converted) == -10.25);
  CHECK(zs407_db32_from_double(INFINITY, &converted) ==
        ZS407_CORE_INVALID_ARGUMENT);

  const zs407_db32_t flat[] = {-960, -960}; /* Two -30 dBm bins. */
  zs407_db32_t scratch[8];
  zs407_measurement_summary_t summary;
  CHECK(zs407_summarize_trace(flat, 2U, 1000U, 1000U, 9900U,
                              scratch, 8U, &summary) == ZS407_CORE_OK);
  CHECK((summary.flags & ZS407_MEASUREMENT_POWER_VALID) != 0U);
  CHECK(summary.integrated_power_dbm32 >= -865);
  CHECK(summary.integrated_power_dbm32 <= -863);
  CHECK(summary.noise_db32 == -960);

  const zs407_db32_t peaked[] = {-3200, -3200, -640, -3200, -3200};
  CHECK(zs407_summarize_trace(peaked, 5U, 100U, 100U, 9900U,
                              scratch, 8U, &summary) == ZS407_CORE_OK);
  CHECK(summary.peak_index == 2U);
  CHECK(summary.occupied_start_index == 2U);
  CHECK(summary.occupied_stop_index == 2U);
  CHECK((summary.flags & ZS407_MEASUREMENT_PEAK_INTERPOLATED) != 0U);

  const zs407_db32_t gaps[] = {-1000, ZS407_TRACE_INVALID_SAMPLE, -900};
  CHECK(zs407_summarize_trace(gaps, 3U, 1U, 1U, 9000U,
                              scratch, 8U, &summary) == ZS407_CORE_OK);
  CHECK((summary.flags & ZS407_MEASUREMENT_HAS_GAPS) != 0U);
  CHECK(summary.valid_points == 2U);
  return 0;
}

static int test_fft(void)
{
  int16_t real[512];
  int16_t imag[512];
  CHECK(zs407_fft_selftest(real, imag, 512U) == 0U);

  for (size_t i = 0U; i < 512U; ++i) {
    real[i] = (i & 1U) == 0U ? 16000 : -16000;
    imag[i] = 0;
  }
  CHECK(zs407_fft_q15(real, imag, 9U) == ZS407_CORE_OK);
  uint32_t maximum = 0U;
  size_t maximum_bin = 0U;
  for (size_t i = 0U; i < 512U; ++i) {
    uint32_t magnitude = zs407_fft_magnitude_squared_q30(real[i], imag[i]);
    if (magnitude > maximum) {
      maximum = magnitude;
      maximum_bin = i;
    }
  }
  CHECK(maximum_bin == 256U);
  CHECK(real[256] > 15000);

  for (size_t i = 0U; i < 256U; ++i) {
    double phase = 2.0 * 3.14159265358979323846 * 37.0 * (double)i / 256.0;
    real[i] = (int16_t)lrint(12000.0 * cos(phase));
    imag[i] = 0;
  }
  CHECK(zs407_fft_q15(real, imag, 8U) == ZS407_CORE_OK);
  maximum = 0U;
  maximum_bin = 0U;
  for (size_t i = 1U; i < 128U; ++i) {
    uint32_t magnitude = zs407_fft_magnitude_squared_q30(real[i], imag[i]);
    if (magnitude > maximum) {
      maximum = magnitude;
      maximum_bin = i;
    }
  }
  CHECK(maximum_bin == 37U);
  CHECK(zs407_fft_q15(real, imag, 7U) == ZS407_CORE_INVALID_ARGUMENT);
  CHECK(zs407_q15_saturate(40000) == 32767);
  CHECK(zs407_q15_saturate(-40000) == -32768);
  return 0;
}

static int test_ui_model(void)
{
  CHECK(zs407_ui_model_selftest() == 0U);
  zs407_dirty_tiles_t tiles;
  zs407_dirty_tiles_all(&tiles);
  unsigned count = 0U;
  uint16_t tile = 0U;
  while (zs407_dirty_tiles_pop(&tiles, &tile)) {
    CHECK(tile < ZS407_UI_TILE_COUNT);
    ++count;
  }
  CHECK(count == ZS407_UI_TILE_COUNT);

  const zs407_db32_t samples[] = {
      -100, 50, -80, ZS407_TRACE_INVALID_SAMPLE, -90, -70, 40, -60};
  zs407_db32_t low[2];
  zs407_db32_t high[2];
  CHECK(zs407_trace_envelope(samples, 8U, 2U, low, high) == ZS407_CORE_OK);
  CHECK(low[0] == -100 && high[0] == 50);
  CHECK(low[1] == -90 && high[1] == 40);
  return 0;
}

static int test_rf_lab(void)
{
  zs407_si4468_hop_plan_t si;
  CHECK(zs407_si4468_hop_plan(UINT64_C(1000000000), UINT64_C(3000000000),
                              &si) == ZS407_CORE_OK);
  CHECK(si.band == 0U);
  CHECK(si.divider == 4U);
  CHECK(si.integer == 65U);
  CHECK(si.fraction >= 524288U && si.fraction < 1048576U);
  CHECK(si.actual_hz >= UINT64_C(999999990));
  CHECK(si.actual_hz <= UINT64_C(1000000010));
  CHECK(si.vco_estimate_in_range);
  CHECK(zs407_si4468_hop_plan(UINT64_C(200000000), UINT64_C(3000000000),
                              &si) == ZS407_CORE_OUT_OF_RANGE);

  zs407_max2871_plan_t max;
  CHECK(zs407_max2871_plan(UINT64_C(3000000000), UINT64_C(3000000000),
                           60U, &max) == ZS407_CORE_OK);
  CHECK(max.divider == 1U && max.divider_code == 0U);
  CHECK(max.integer == 100U && max.fraction == 0U);
  CHECK(max.actual_hz == UINT64_C(3000000000));
  CHECK((max.register0 & 7U) == 0U);
  CHECK((max.register1 & 7U) == 1U);
  CHECK(zs407_max2871_plan(UINT64_C(100000000), UINT64_C(3000000000),
                           60U, &max) == ZS407_CORE_OK);
  CHECK(max.divider == 64U && max.divider_code == 6U);

  const zs407_db32_t coarse[] = {
      -3200, -3100, -1000, -3150, -3200, -3000, -900, -2900, -3200};
  zs407_refinement_window_t windows[4];
  size_t window_count = 0U;
  CHECK(zs407_select_refinement_windows(coarse, 9U, -3000, 1000, 1U,
                                        windows, 4U, &window_count) ==
        ZS407_CORE_OK);
  CHECK(window_count == 2U);
  CHECK(windows[0].first_index == 1U && windows[0].last_index == 3U &&
        windows[0].peak_index == 2U);
  CHECK(windows[1].first_index == 5U && windows[1].last_index == 7U &&
        windows[1].peak_index == 6U);

  CHECK(zs407_select_refinement_windows(coarse, 9U, -3000, 1000, 1U,
                                        windows, 1U, &window_count) ==
        ZS407_CORE_BUFFER_TOO_SMALL);
  return 0;
}

static int test_waveform(void)
{
  zs407_timer16_plan_t timer;
  CHECK(zs407_timer16_plan(48000000U, 48000U, &timer) == ZS407_CORE_OK);
  CHECK(timer.prescaler == 0U && timer.auto_reload == 999U &&
        timer.actual_rate_hz == 48000U);
  CHECK(zs407_timer16_plan(48000000U, 44100U, &timer) == ZS407_CORE_OK);
  CHECK(timer.prescaler == 0U && timer.auto_reload == 1087U &&
        timer.actual_rate_hz == 44118U);
  CHECK(zs407_timer16_plan(48000000U, 0U, &timer) ==
        ZS407_CORE_INVALID_ARGUMENT);
  for (uint32_t requested = 100U; requested <= 200000U;
       requested += 137U) {
    CHECK(zs407_timer16_plan(48000000U, requested, &timer) == ZS407_CORE_OK);
    uint64_t divisor = (uint64_t)(timer.prescaler + 1U) *
                       (uint64_t)(timer.auto_reload + 1U);
    uint32_t expected =
        (uint32_t)((UINT64_C(48000000) + divisor / 2U) / divisor);
    CHECK(timer.actual_rate_hz == expected);
  }

  CHECK(zs407_sine_q15(0U) == 0);
  CHECK(zs407_sine_q15(UINT32_C(0x40000000)) == 32767);
  CHECK(zs407_sine_q15(UINT32_C(0x80000000)) == 0);
  CHECK(zs407_sine_q15(UINT32_C(0xc0000000)) == -32767);

  uint16_t samples[64];
  zs407_wave_oscillator_t oscillator = {0U, UINT32_C(0x12345678)};
  uint32_t actual_millihz = 0U;
  CHECK(zs407_render_dac12(ZS407_WAVE_SINE, 1000000U, 32000U, 1800U,
                           2048U, &oscillator, samples, 32U,
                           &actual_millihz) == ZS407_CORE_OK);
  CHECK(actual_millihz == 1000000U);
  CHECK(samples[0] == 2048U);
  CHECK(samples[8] >= 3847U && samples[8] <= 3848U);
  CHECK(samples[24] >= 247U && samples[24] <= 249U);

  oscillator.phase = 0U;
  CHECK(zs407_render_dac12(ZS407_WAVE_TRIANGLE, 500000U, 32000U,
                           2048U, 2048U, &oscillator, samples, 64U,
                           &actual_millihz) == ZS407_CORE_OK);
  for (size_t i = 0U; i < 64U; ++i) {
    CHECK(samples[i] <= 4095U);
  }
  for (unsigned shape = ZS407_WAVE_SINE; shape <= ZS407_WAVE_NOISE;
       ++shape) {
    oscillator.phase = UINT32_C(0x10203040);
    oscillator.noise_state = UINT32_C(0x12345678);
    CHECK(zs407_render_dac12((zs407_wave_shape_t)shape, 750000U,
                             48000U, 4095U, 2048U, &oscillator, samples,
                             64U, &actual_millihz) == ZS407_CORE_OK);
    for (size_t i = 0U; i < 64U; ++i) {
      CHECK(samples[i] <= 4095U);
    }
  }

  const zs407_wave_event_t program[] = {
      {0U, ZS407_EVENT_GATE, 0U, 0U, 0},
      {0U, ZS407_EVENT_SET_FREQUENCY_HZ, 0U, 0U, 100000000},
      {0U, ZS407_EVENT_SET_LEVEL_DBM_X10, 0U, 0U, -300},
      {1000U, ZS407_EVENT_GATE, 0U, 0U, 1},
      {11000U, ZS407_EVENT_GATE, 0U, 0U, 0},
      {11000U, ZS407_EVENT_END, 0U, 0U, 0},
  };
  zs407_wave_program_report_t report;
  CHECK(zs407_validate_wave_program(program, 6U, &report) == ZS407_CORE_OK);
  CHECK(report.duration_us == 11000U);
  CHECK(report.maximum_frequency_hz == 100000000U);
  CHECK(report.gate_transitions == 2U);
  CHECK(report.minimum_level_dbm_x10 == -300);

  zs407_wave_event_t unsafe[2] = {
      {0U, ZS407_EVENT_GATE, 0U, 0U, 1},
      {1U, ZS407_EVENT_END, 0U, 0U, 0},
  };
  CHECK(zs407_validate_wave_program(unsafe, 2U, &report) ==
        ZS407_CORE_NOT_QUALIFIED);
  unsafe[0] = (zs407_wave_event_t){0U, ZS407_EVENT_GATE, 0U, 0U, 0};
  unsafe[1] = (zs407_wave_event_t){1U, ZS407_EVENT_WAIT_TRIGGER, 0U, 0U, 0};
  CHECK(zs407_validate_wave_program(unsafe, 2U, &report) ==
        ZS407_CORE_NOT_QUALIFIED);

  zs407_wave_event_t trigger_program[4] = {
      {0U, ZS407_EVENT_GATE, 0U, 0U, 0},
      {1U, ZS407_EVENT_GATE, 0U, 0U, 1},
      {2U, ZS407_EVENT_WAIT_TRIGGER, 0U, 0U, 0},
      {3U, ZS407_EVENT_END, 0U, 0U, 0},
  };
  CHECK(zs407_validate_wave_program(trigger_program, 4U, &report) ==
        ZS407_CORE_NOT_QUALIFIED);
  trigger_program[1].value = 0;
  trigger_program[2].reserved = 1U;
  CHECK(zs407_validate_wave_program(trigger_program, 4U, &report) ==
        ZS407_CORE_INVALID_ARGUMENT);

  zs407_rf_fifo_plan_t fifo;
  CHECK(zs407_rf_fifo_plan(ZS407_RF_MOD_2GFSK, 9600U, 5000U, 32U,
                           &fifo) == ZS407_CORE_OK);
  CHECK(fifo.symbol_rate == 9600U && fifo.bits_per_symbol == 1U);
  CHECK(zs407_rf_fifo_plan(ZS407_RF_MOD_4FSK, 9600U, 5000U, 64U,
                           &fifo) == ZS407_CORE_OK);
  CHECK(fifo.symbol_rate == 4800U && fifo.bits_per_symbol == 2U);
  CHECK(zs407_rf_fifo_plan(ZS407_RF_MOD_2FSK, 9600U, 0U, 64U,
                           &fifo) == ZS407_CORE_INVALID_ARGUMENT);
  CHECK(zs407_rf_fifo_plan(ZS407_RF_MOD_OOK, 1000001U, 0U, 64U,
                           &fifo) == ZS407_CORE_INVALID_ARGUMENT);

  uint8_t code = 0U;
  zs407_db32_t actual = 0;
  CHECK(zs407_quantize_pe4302_db32(168, &code, &actual) == ZS407_CORE_OK);
  CHECK(code == 11U && actual == 176);
  CHECK(zs407_quantize_pe4302_db32(0, &code, &actual) == ZS407_CORE_OK);
  CHECK(code == 0U && actual == 0);
  CHECK(zs407_quantize_pe4302_db32(1008, &code, &actual) == ZS407_CORE_OK);
  CHECK(code == 63U && actual == 1008);
  CHECK(zs407_quantize_pe4302_db32(1024, &code, &actual) ==
        ZS407_CORE_OUT_OF_RANGE);
  return 0;
}

int main(int argc, char **argv)
{
  if (argc != 2) {
    fprintf(stderr, "usage: %s protocol-fixture.hex\n", argv[0]);
    return 2;
  }
  CHECK(test_contract() == 0);
  CHECK(test_frequency_dda() == 0);
  CHECK(test_fixed_point_and_correction() == 0);
  CHECK(test_statistics() == 0);
  CHECK(test_protocol(argv[1]) == 0);
  CHECK(test_services() == 0);
  CHECK(test_measurements() == 0);
  CHECK(test_fft() == 0);
  CHECK(test_ui_model() == 0);
  CHECK(test_rf_lab() == 0);
  CHECK(test_waveform() == 0);
  puts("ZS407 host core: all tests passed");
  return 0;
}
