/* SPDX-License-Identifier: GPL-3.0-or-later */
#include "modern/core/zs407_fft.h"

#include <errno.h>
#include <limits.h>
#include <stdio.h>
#include <stdlib.h>

int main(int argc, char **argv)
{
  int16_t real[256] = {0};
  int16_t imaginary[256] = {0};
  char *end = NULL;
  long amplitude;
  unsigned long index;

  if (argc != 3) {
    return 2;
  }
  errno = 0;
  amplitude = strtol(argv[1], &end, 10);
  if (errno != 0 || end == argv[1] || *end != '\0' ||
      amplitude < INT16_MIN || amplitude > INT16_MAX) {
    return 2;
  }
  errno = 0;
  index = strtoul(argv[2], &end, 10);
  if (errno != 0 || end == argv[2] || *end != '\0' || index >= 256UL) {
    return 2;
  }

  real[index] = (int16_t)amplitude;
  if (zs407_fft_q15(real, imaginary, 8U) != ZS407_CORE_OK) {
    return 3;
  }
  for (size_t position = 0U; position < 256U; ++position) {
    if (printf("%d %d\n", (int)real[position],
               (int)imaginary[position]) < 0) {
      return 4;
    }
  }
  return 0;
}
