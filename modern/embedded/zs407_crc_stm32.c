/* SPDX-License-Identifier: GPL-3.0-or-later */
#include "zs407_crc_stm32.h"

#include "ch.h"
#include "hal.h"

/*
 * RM0316 6.3/6.4: byte writes take one AHB cycle, REV_IN=byte and REV_OUT
 * map the programmable 0x04c11db7 engine to reflected IEEE CRC-32. The
 * peripheral is global state, so ownership is claimed briefly under the
 * kernel lock and computation itself runs with interrupts enabled.
 */
static volatile bool crc_busy;
static volatile uint32_t successful_selftests;
static volatile uint32_t failed_selftests;

static bool acquire_crc(void)
{
  bool acquired = false;
  chSysLock();
  if (!crc_busy) {
    crc_busy = true;
    RCC->AHBENR |= RCC_AHBENR_CRCEN;
    (void)RCC->AHBENR;
    acquired = true;
  }
  chSysUnlock();
  return acquired;
}

static void release_crc(void)
{
  chSysLock();
  crc_busy = false;
  chSysUnlock();
}

bool zs407_crc32_stm32_try(const uint8_t *data, size_t length,
                           uint32_t *result)
{
  if (result == NULL || (data == NULL && length != 0U) || !acquire_crc()) {
    return false;
  }
  CRC->POL = UINT32_C(0x04c11db7);
  CRC->INIT = UINT32_C(0xffffffff);
  CRC->CR = CRC_CR_REV_IN_0 | CRC_CR_REV_OUT | CRC_CR_RESET;
  volatile uint8_t *data_register =
      (volatile uint8_t *)(void *)&CRC->DR;
  for (size_t i = 0U; i < length; ++i) {
    *data_register = data[i];
  }
  *result = CRC->DR ^ UINT32_C(0xffffffff);
  release_crc();
  return true;
}

uint32_t zs407_crc32_stm32_selftest(void)
{
  static const uint8_t check[] = "123456789";
  uint32_t result = 0U;
  uint32_t failures =
      !zs407_crc32_stm32_try(check, sizeof(check) - 1U, &result) ? 1U : 0U;
  if (result != UINT32_C(0xcbf43926)) {
    failures |= 2U;
  }
  chSysLock();
  if (failures == 0U) {
    successful_selftests++;
  } else {
    failed_selftests++;
  }
  chSysUnlock();
  return failures;
}

void zs407_crc32_stm32_status(zs407_crc_stm32_status_t *status)
{
  if (status != NULL) {
    status->available = true;
    status->busy = crc_busy;
    /* Deliberately no setter: hardware comparison is required first. */
    status->hardware_qualified = false;
    status->successful_selftests = successful_selftests;
    status->failed_selftests = failed_selftests;
  }
}
