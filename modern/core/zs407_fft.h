/* SPDX-License-Identifier: GPL-3.0-or-later */
#ifndef ZS407_FFT_H
#define ZS407_FFT_H

#include "zs407_core.h"

#define ZS407_FFT_MIN_LOG2 8U
#define ZS407_FFT_MAX_LOG2 10U
#define ZS407_FFT_MAX_POINTS (1U << ZS407_FFT_MAX_LOG2)

int16_t zs407_q15_saturate(int32_t value);
zs407_core_status_t zs407_fft_q15(int16_t *real, int16_t *imag,
                                  uint8_t log2_points);
uint32_t zs407_fft_magnitude_squared_q30(int16_t real, int16_t imag);
uint32_t zs407_fft_selftest(int16_t *real, int16_t *imag,
                            size_t scratch_points);

#endif /* ZS407_FFT_H */
