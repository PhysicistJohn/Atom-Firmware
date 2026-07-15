/* SPDX-License-Identifier: GPL-3.0-or-later */
#include "zs407_awg.h"

#include "ch.h"
#include "hal.h"

#include "../../nanovna.h"
#include "../core/zs407_protocol.h"

#include <string.h>

/*
 * DMA cannot read CCM on STM32F303, so this deliberately lives in ordinary
 * SRAM. The only qualification latch is private and has no setter in Phase 5.
 * Volatile keeps the complete hardware path in the linked image for compile
 * checking while every shipped Phase 5 invocation returns NOT_QUALIFIED.
 */
static uint16_t awg_samples[ZS407_AWG_SAMPLE_COUNT]
    __attribute__((aligned(4)));
static zs407_awg_status_t awg_status;
static zs407_timer16_plan_t awg_timer;
static volatile bool awg_hardware_qualified;
static const stm32_dma_stream_t *awg_dma;

zs407_core_status_t zs407_awg_prepare(zs407_wave_shape_t shape,
                                      uint32_t frequency_millihz,
                                      uint32_t sample_rate_hz,
                                      uint16_t amplitude, uint16_t offset)
{
  if (awg_status.active) {
    return ZS407_CORE_NOT_QUALIFIED;
  }
  memset(&awg_status, 0, sizeof(awg_status));
  awg_status.hardware_qualified = awg_hardware_qualified;
  if (sample_rate_hz < ZS407_AWG_MIN_SAMPLE_RATE_HZ ||
      sample_rate_hz > ZS407_AWG_MAX_SAMPLE_RATE_HZ) {
    return ZS407_CORE_OUT_OF_RANGE;
  }
  zs407_core_status_t result =
      zs407_timer16_plan(STM32_TIMCLK1, sample_rate_hz, &awg_timer);
  if (result != ZS407_CORE_OK) {
    return result;
  }

  zs407_wave_oscillator_t oscillator = {
      .phase = 0U, .noise_state = UINT32_C(0x4075a17e)};
  uint32_t actual_frequency_millihz;
  result = zs407_render_dac12(
      shape, frequency_millihz, awg_timer.actual_rate_hz, amplitude, offset,
      &oscillator, awg_samples, ZS407_AWG_SAMPLE_COUNT,
      &actual_frequency_millihz);
  if (result != ZS407_CORE_OK) {
    return result;
  }

  awg_status.requested_frequency_millihz = frequency_millihz;
  awg_status.actual_frequency_millihz = actual_frequency_millihz;
  awg_status.requested_sample_rate_hz = sample_rate_hz;
  awg_status.actual_sample_rate_hz = awg_timer.actual_rate_hz;
  awg_status.buffer_crc32 =
      zs407_crc32((const uint8_t *)awg_samples, sizeof(awg_samples));
  awg_status.amplitude = amplitude;
  awg_status.offset = offset;
  awg_status.sample_count = ZS407_AWG_SAMPLE_COUNT;
  awg_status.shape = (uint8_t)shape;
  awg_status.prepared = true;
  awg_status.hardware_qualified = awg_hardware_qualified;
  return ZS407_CORE_OK;
}

zs407_core_status_t zs407_awg_start(void)
{
  if (!awg_hardware_qualified) {
    return ZS407_CORE_NOT_QUALIFIED;
  }
  if (!awg_status.prepared || awg_status.active) {
    return ZS407_CORE_INVALID_ARGUMENT;
  }
  awg_dma = dmaStreamAlloc(STM32_DAC_DAC1_CH1_DMA_STREAM, 2U, NULL, NULL);
  if (awg_dma == NULL) {
    return ZS407_CORE_UNSUPPORTED;
  }

  set_audio_mode(A_DAC);
  palSetPadMode(GPIOA, 4U, PAL_MODE_INPUT_ANALOG);
  rccEnableDAC1(false);
  rccEnableTIM6(false);
  rccResetTIM6();

  TIM6->CR1 = 0U;
  TIM6->CR2 = TIM_CR2_MMS_1;
  TIM6->PSC = awg_timer.prescaler;
  TIM6->ARR = awg_timer.auto_reload;
  TIM6->EGR = TIM_EGR_UG;

  DAC->CR &= ~(DAC_CR_EN1 | DAC_CR_BOFF1 | DAC_CR_TEN1 | DAC_CR_TSEL1 |
               DAC_CR_WAVE1 | DAC_CR_MAMP1 | DAC_CR_DMAEN1 |
               DAC_CR_DMAUDRIE1);
  DAC->SR = DAC_SR_DMAUDR1;
  DAC->DHR12R1 = awg_samples[0];

  dmaStreamSetPeripheral(awg_dma, &DAC->DHR12R1);
  dmaStreamSetMemory0(awg_dma, awg_samples);
  dmaStreamSetTransactionSize(awg_dma, ZS407_AWG_SAMPLE_COUNT);
  dmaStreamSetMode(awg_dma, STM32_DMA_CR_DIR_M2P | STM32_DMA_CR_CIRC |
                                STM32_DMA_CR_MINC |
                                STM32_DMA_CR_PSIZE_HWORD |
                                STM32_DMA_CR_MSIZE_HWORD |
                                STM32_DMA_CR_PL(2));

  DAC->CR |= DAC_CR_EN1 | DAC_CR_TEN1 | DAC_CR_DMAEN1;
  dmaStreamEnable(awg_dma);
  TIM6->CR1 = TIM_CR1_CEN;
  awg_status.active = true;
  return ZS407_CORE_OK;
}

void zs407_awg_stop(void)
{
  if (!awg_status.active) {
    return;
  }
  TIM6->CR1 = 0U;
  DAC->CR &= ~(DAC_CR_TEN1 | DAC_CR_DMAEN1 | DAC_CR_DMAUDRIE1);
  dmaStreamDisable(awg_dma);
  dmaStreamFree(awg_dma);
  awg_dma = NULL;
  DAC->DHR12R1 = 0U;
  rccDisableTIM6();
  awg_status.active = false;
}

void zs407_awg_get_status(zs407_awg_status_t *status)
{
  if (status == NULL) {
    return;
  }
  *status = awg_status;
  status->hardware_qualified = awg_hardware_qualified;
}

uint32_t zs407_awg_selftest(void)
{
  uint32_t failures = 0U;
  if (awg_status.active) {
    return UINT32_C(0x80000000);
  }
  if (zs407_awg_prepare(ZS407_WAVE_SINE, 1000000U, 48000U, 1800U,
                        2048U) != ZS407_CORE_OK) {
    failures |= 1U;
  }
  if (!awg_status.prepared || awg_status.actual_sample_rate_hz != 48000U ||
      awg_status.sample_count != ZS407_AWG_SAMPLE_COUNT ||
      awg_status.buffer_crc32 == 0U) {
    failures |= 2U;
  }
  if (zs407_awg_start() != ZS407_CORE_NOT_QUALIFIED || awg_status.active) {
    failures |= 4U;
  }
  return failures;
}
