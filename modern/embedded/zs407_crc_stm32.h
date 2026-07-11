/* SPDX-License-Identifier: GPL-3.0-or-later */
#ifndef ZS407_CRC_STM32_H
#define ZS407_CRC_STM32_H

#include "../core/zs407_core.h"

typedef struct {
  bool available;
  bool busy;
  bool hardware_qualified;
  uint32_t successful_selftests;
  uint32_t failed_selftests;
} zs407_crc_stm32_status_t;

bool zs407_crc32_stm32_try(const uint8_t *data, size_t length,
                           uint32_t *result);
uint32_t zs407_crc32_stm32_selftest(void);
void zs407_crc32_stm32_status(zs407_crc_stm32_status_t *status);

#endif /* ZS407_CRC_STM32_H */
