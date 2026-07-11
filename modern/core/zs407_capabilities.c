/* SPDX-License-Identifier: GPL-3.0-or-later */
#include "zs407_capabilities.h"

#include <string.h>

#define ZS407_PHASE6_FEATURES                                              \
  (ZS407_CAP_EXACT_BASELINE | ZS407_CAP_SAFE_TIMING |                     \
   ZS407_CAP_HOST_CONTRACT | ZS407_CAP_HARD_FAULT_VENEER |                \
   ZS407_CAP_DETERMINISTIC_SERVICES | ZS407_CAP_CCM_SCRATCH |             \
   ZS407_CAP_FIXED_POINT_DSP | ZS407_CAP_ATOMIC_UI_MODEL |                \
   ZS407_CAP_RF_DRY_RUN_LAB | ZS407_CAP_WAVEFORM_FOUNDATION |             \
   ZS407_CAP_FINAL_DISPOSITION_AUDIT)

_Static_assert(sizeof(zs407_release_manifest_t) == 20U,
               "release manifest ABI changed");

zs407_core_status_t zs407_release_manifest_for_phase(
    uint8_t phase, zs407_release_manifest_t *manifest)
{
  if (manifest == NULL || phase > 6U) {
    return ZS407_CORE_INVALID_ARGUMENT;
  }
  memset(manifest, 0, sizeof(*manifest));
  manifest->manifest_schema = ZS407_RELEASE_MANIFEST_SCHEMA;
  manifest->phase = phase;
  manifest->protocol_version = ZS407_PROTOCOL_VERSION;
  manifest->maximum_sweep_points = 450U;
  manifest->feature_bits = ZS407_CAP_EXACT_BASELINE | ZS407_CAP_SAFE_TIMING;
  manifest->safety_bits = ZS407_SAFETY_HARDWARE_UNQUALIFIED |
                          ZS407_SAFETY_NO_AUTOMATED_FLASH;
  if (phase >= 1U) {
    manifest->feature_bits |=
        ZS407_CAP_HOST_CONTRACT | ZS407_CAP_HARD_FAULT_VENEER;
  }
  if (phase >= 2U) {
    manifest->feature_bits |=
        ZS407_CAP_DETERMINISTIC_SERVICES | ZS407_CAP_CCM_SCRATCH;
  }
  if (phase >= 3U) {
    manifest->feature_bits |=
        ZS407_CAP_FIXED_POINT_DSP | ZS407_CAP_ATOMIC_UI_MODEL;
    manifest->maximum_fft_points = 512U;
  }
  if (phase >= 4U) {
    manifest->feature_bits |= ZS407_CAP_RF_DRY_RUN_LAB;
    manifest->safety_bits |= ZS407_SAFETY_RF_EXPERIMENTS_DISABLED;
  }
  if (phase >= 5U) {
    manifest->feature_bits |= ZS407_CAP_WAVEFORM_FOUNDATION;
    manifest->safety_bits |= ZS407_SAFETY_AWG_EXECUTION_LOCKED;
    manifest->waveform_sample_count = 256U;
    manifest->waveform_event_bytes = 16U;
  }
  if (phase >= 6U) {
    manifest->feature_bits |= ZS407_CAP_FINAL_DISPOSITION_AUDIT;
  }
  return ZS407_CORE_OK;
}

uint32_t zs407_capabilities_selftest(void)
{
  uint32_t failures = 0U;
  uint32_t previous = 0U;
  for (uint8_t phase = 0U; phase <= 6U; ++phase) {
    zs407_release_manifest_t manifest;
    if (zs407_release_manifest_for_phase(phase, &manifest) != ZS407_CORE_OK) {
      failures |= 1U;
      continue;
    }
    if (manifest.manifest_schema != ZS407_RELEASE_MANIFEST_SCHEMA ||
        manifest.phase != phase ||
        manifest.protocol_version != ZS407_PROTOCOL_VERSION ||
        (manifest.feature_bits & previous) != previous) {
      failures |= 2U;
    }
    if ((phase < 3U) != (manifest.maximum_fft_points == 0U) ||
        (phase < 5U) != (manifest.waveform_sample_count == 0U)) {
      failures |= 4U;
    }
    previous = manifest.feature_bits;
  }
  zs407_release_manifest_t final_manifest;
  if (zs407_release_manifest_for_phase(6U, &final_manifest) != ZS407_CORE_OK ||
      final_manifest.feature_bits != ZS407_PHASE6_FEATURES ||
      final_manifest.safety_bits !=
          (ZS407_SAFETY_HARDWARE_UNQUALIFIED |
           ZS407_SAFETY_NO_AUTOMATED_FLASH |
           ZS407_SAFETY_RF_EXPERIMENTS_DISABLED |
           ZS407_SAFETY_AWG_EXECUTION_LOCKED) ||
      final_manifest.maximum_fft_points != 512U ||
      final_manifest.waveform_event_bytes != 16U) {
    failures |= 8U;
  }
  if (zs407_release_manifest_for_phase(7U, &final_manifest) !=
          ZS407_CORE_INVALID_ARGUMENT ||
      zs407_release_manifest_for_phase(0U, NULL) !=
          ZS407_CORE_INVALID_ARGUMENT) {
    failures |= 16U;
  }
  return failures;
}
