/* SPDX-License-Identifier: GPL-3.0-or-later */
#include "zs407_fft.h"

#include <limits.h>

typedef struct {
  int16_t real;
  int16_t imag;
} q15_complex_t;

/* exp(-j*2*pi/(2^stage)), rounded to Q1.15. */
static const q15_complex_t stage_step[ZS407_FFT_MAX_LOG2 + 1U] = {
    {0, 0},          {-32768, 0},   {0, -32768},    {23170, -23170},
    {30274, -12540}, {32138, -6393}, {32610, -3212}, {32729, -1608},
    {32758, -804},   {32766, -402}};

int16_t zs407_q15_saturate(int32_t value)
{
  if (value > INT16_MAX) {
    return INT16_MAX;
  }
  if (value < INT16_MIN) {
    return INT16_MIN;
  }
  return (int16_t)value;
}

static int16_t q15_round(int64_t value)
{
  value += value >= 0 ? INT64_C(16384) : -INT64_C(16384);
  return zs407_q15_saturate((int32_t)(value / INT64_C(32768)));
}

static unsigned reverse_bits(unsigned value, uint8_t bits)
{
  unsigned reversed = 0U;
  for (uint8_t bit = 0U; bit < bits; ++bit) {
    reversed = (reversed << 1) | (value & 1U);
    value >>= 1;
  }
  return reversed;
}

zs407_core_status_t zs407_fft_q15(int16_t *real, int16_t *imag,
                                  uint8_t log2_points)
{
  if (real == NULL || imag == NULL || log2_points < ZS407_FFT_MIN_LOG2 ||
      log2_points > ZS407_FFT_MAX_LOG2) {
    return ZS407_CORE_INVALID_ARGUMENT;
  }
  unsigned points = 1U << log2_points;
  for (unsigned i = 0U; i < points; ++i) {
    unsigned j = reverse_bits(i, log2_points);
    if (j > i) {
      int16_t temp = real[i];
      real[i] = real[j];
      real[j] = temp;
      temp = imag[i];
      imag[i] = imag[j];
      imag[j] = temp;
    }
  }

  for (uint8_t stage = 1U; stage <= log2_points; ++stage) {
    unsigned width = 1U << stage;
    unsigned half = width >> 1;
    int16_t step_real = stage_step[stage].real;
    int16_t step_imag = stage_step[stage].imag;
    int16_t twiddle_real = 32767;
    int16_t twiddle_imag = 0;
    for (unsigned j = 0U; j < half; ++j) {
      for (unsigned i = j; i < points; i += width) {
        unsigned pair = i + half;
        int16_t product_real = q15_round(
            (int64_t)twiddle_real * real[pair] -
            (int64_t)twiddle_imag * imag[pair]);
        int16_t product_imag = q15_round(
            (int64_t)twiddle_real * imag[pair] +
            (int64_t)twiddle_imag * real[pair]);
        int32_t upper_real = real[i];
        int32_t upper_imag = imag[i];
        real[i] = zs407_q15_saturate((upper_real + product_real) / 2);
        imag[i] = zs407_q15_saturate((upper_imag + product_imag) / 2);
        real[pair] = zs407_q15_saturate((upper_real - product_real) / 2);
        imag[pair] = zs407_q15_saturate((upper_imag - product_imag) / 2);
      }
      int16_t next_real = q15_round(
          (int64_t)twiddle_real * step_real -
          (int64_t)twiddle_imag * step_imag);
      int16_t next_imag = q15_round(
          (int64_t)twiddle_real * step_imag +
          (int64_t)twiddle_imag * step_real);
      twiddle_real = next_real;
      twiddle_imag = next_imag;
    }
  }
  return ZS407_CORE_OK;
}

uint32_t zs407_fft_magnitude_squared_q30(int16_t real, int16_t imag)
{
  int64_t r = real;
  int64_t i = imag;
  return (uint32_t)(r * r + i * i);
}

uint32_t zs407_fft_selftest(int16_t *real, int16_t *imag,
                            size_t scratch_points)
{
  if (real == NULL || imag == NULL || scratch_points < 256U) {
    return UINT32_C(1) << 0;
  }
  for (size_t i = 0U; i < 256U; ++i) {
    real[i] = 0;
    imag[i] = 0;
  }
  real[0] = 32767;
  if (zs407_fft_q15(real, imag, 8U) != ZS407_CORE_OK) {
    return UINT32_C(1) << 1;
  }
  for (size_t i = 0U; i < 256U; ++i) {
    if (real[i] < 124 || real[i] > 130 || imag[i] < -2 || imag[i] > 2) {
      return UINT32_C(1) << 2;
    }
  }
  return 0U;
}
