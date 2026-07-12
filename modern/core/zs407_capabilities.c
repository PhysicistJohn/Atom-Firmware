/* SPDX-License-Identifier: GPL-3.0-or-later */
#include "zs407_capabilities.h"
#include "zs407_fft.h"

#include "../../zs407_features.h"

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
    manifest->maximum_fft_points = ZS407_FFT_MAX_POINTS;
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
#if ZS407_RELEASE_PROTOCOL_V2
  if (phase >= 6U) {
    manifest->feature_bits |= ZS407_CAP_TYPED_PROTOCOL_V2 |
                              ZS407_CAP_STREAMING_MARSHALLING |
                              ZS407_CAP_COMPACT_STORAGE_CODECS |
                              ZS407_CAP_ASYNC_USB_LAB;
    manifest->safety_bits |= ZS407_SAFETY_HARDWARE_CRC_UNQUALIFIED;
#if ZS407_RELEASE_TRANSPORT_QUAL
    manifest->feature_bits |= ZS407_CAP_BINARY_TRANSPORT_QUALIFICATION;
    manifest->safety_bits |= ZS407_SAFETY_TRANSPORT_QUALIFICATION_ONLY;
#else
    manifest->safety_bits |= ZS407_SAFETY_BINARY_TRANSPORT_LOCKED;
#endif
  }
#endif
#if ZS407_RELEASE_PASSIVE_V04
  if (phase >= 6U) {
    manifest->feature_bits |= ZS407_CAP_DEVICE_TIMESTAMPS |
                              ZS407_CAP_PASSIVE_STREAM_ENGINE |
                              ZS407_CAP_ADAPTIVE_SCAN_PLANNER |
                              ZS407_CAP_ZERO_SPAN_FFT_CAPTURE;
    manifest->safety_bits |= ZS407_SAFETY_PASSIVE_EXECUTION_LOCKED |
                             ZS407_SAFETY_CLOCK_NOT_DISCIPLINED |
                             ZS407_SAFETY_ADAPTIVE_EXECUTION_LOCKED;
  }
#endif
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
      final_manifest.feature_bits !=
          (ZS407_PHASE6_FEATURES
#if ZS407_RELEASE_PROTOCOL_V2
           | ZS407_CAP_TYPED_PROTOCOL_V2 |
             ZS407_CAP_STREAMING_MARSHALLING |
             ZS407_CAP_COMPACT_STORAGE_CODECS | ZS407_CAP_ASYNC_USB_LAB
#if ZS407_RELEASE_TRANSPORT_QUAL
           | ZS407_CAP_BINARY_TRANSPORT_QUALIFICATION
#endif
#endif
#if ZS407_RELEASE_PASSIVE_V04
           | ZS407_CAP_DEVICE_TIMESTAMPS |
             ZS407_CAP_PASSIVE_STREAM_ENGINE |
             ZS407_CAP_ADAPTIVE_SCAN_PLANNER |
             ZS407_CAP_ZERO_SPAN_FFT_CAPTURE
#endif
          ) ||
      final_manifest.safety_bits !=
          (ZS407_SAFETY_HARDWARE_UNQUALIFIED |
           ZS407_SAFETY_NO_AUTOMATED_FLASH |
           ZS407_SAFETY_RF_EXPERIMENTS_DISABLED |
           ZS407_SAFETY_AWG_EXECUTION_LOCKED
#if ZS407_RELEASE_PROTOCOL_V2
           | ZS407_SAFETY_HARDWARE_CRC_UNQUALIFIED
#if ZS407_RELEASE_TRANSPORT_QUAL
           | ZS407_SAFETY_TRANSPORT_QUALIFICATION_ONLY
#else
           | ZS407_SAFETY_BINARY_TRANSPORT_LOCKED
#endif
#endif
#if ZS407_RELEASE_PASSIVE_V04
           | ZS407_SAFETY_PASSIVE_EXECUTION_LOCKED |
             ZS407_SAFETY_CLOCK_NOT_DISCIPLINED |
             ZS407_SAFETY_ADAPTIVE_EXECUTION_LOCKED
#endif
          ) ||
      final_manifest.maximum_fft_points != ZS407_FFT_MAX_POINTS ||
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
