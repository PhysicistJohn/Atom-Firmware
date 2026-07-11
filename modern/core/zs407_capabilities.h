/* SPDX-License-Identifier: GPL-3.0-or-later */
#ifndef ZS407_CAPABILITIES_H
#define ZS407_CAPABILITIES_H

#include "zs407_core.h"

#define ZS407_RELEASE_MANIFEST_SCHEMA 1U

enum {
  ZS407_CAP_EXACT_BASELINE = UINT32_C(1) << 0,
  ZS407_CAP_SAFE_TIMING = UINT32_C(1) << 1,
  ZS407_CAP_HOST_CONTRACT = UINT32_C(1) << 2,
  ZS407_CAP_HARD_FAULT_VENEER = UINT32_C(1) << 3,
  ZS407_CAP_DETERMINISTIC_SERVICES = UINT32_C(1) << 4,
  ZS407_CAP_CCM_SCRATCH = UINT32_C(1) << 5,
  ZS407_CAP_FIXED_POINT_DSP = UINT32_C(1) << 6,
  ZS407_CAP_ATOMIC_UI_MODEL = UINT32_C(1) << 7,
  ZS407_CAP_RF_DRY_RUN_LAB = UINT32_C(1) << 8,
  ZS407_CAP_WAVEFORM_FOUNDATION = UINT32_C(1) << 9,
  ZS407_CAP_FINAL_DISPOSITION_AUDIT = UINT32_C(1) << 10
};

enum {
  ZS407_SAFETY_HARDWARE_UNQUALIFIED = UINT32_C(1) << 0,
  ZS407_SAFETY_NO_AUTOMATED_FLASH = UINT32_C(1) << 1,
  ZS407_SAFETY_RF_EXPERIMENTS_DISABLED = UINT32_C(1) << 2,
  ZS407_SAFETY_AWG_EXECUTION_LOCKED = UINT32_C(1) << 3
};

typedef struct {
  uint32_t feature_bits;
  uint32_t safety_bits;
  uint16_t protocol_version;
  uint16_t maximum_sweep_points;
  uint16_t maximum_fft_points;
  uint16_t waveform_sample_count;
  uint16_t waveform_event_bytes;
  uint8_t manifest_schema;
  uint8_t phase;
} zs407_release_manifest_t;

zs407_core_status_t zs407_release_manifest_for_phase(
    uint8_t phase, zs407_release_manifest_t *manifest);
uint32_t zs407_capabilities_selftest(void);

#endif /* ZS407_CAPABILITIES_H */
