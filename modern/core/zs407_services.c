/* SPDX-License-Identifier: GPL-3.0-or-later */
#include "zs407_services.h"

#include <limits.h>
#include <string.h>

bool zs407_hardware_caps(uint16_t hardware_id, zs407_hardware_caps_t *caps)
{
  if (caps == NULL) {
    return false;
  }
  memset(caps, 0, sizeof(*caps));
  caps->hardware_id = hardware_id;
  switch (hardware_id) {
  case 1U:
  case 2U:
    caps->first_if_hz = 977400000U;
    caps->normal_input_max_hz = 800000000U;
    caps->synthesized_limit_hz = UINT64_C(5327400000);
    return true;
  case 3U:
    caps->first_if_hz = 1070100000U;
    caps->normal_input_max_hz = 900000000U;
    caps->synthesized_limit_hz = UINT64_C(5420100000);
    caps->has_plus_if = true;
    return true;
  case 103U:
    caps->first_if_hz = 1070100000U;
    caps->normal_input_max_hz = 900000000U;
    caps->synthesized_limit_hz = UINT64_C(7370100000);
    caps->has_plus_if = true;
    caps->has_max2871 = true;
    return true;
  default:
    return false;
  }
}

uint32_t zs407_rf_state_diff(const zs407_rf_state_t *previous,
                             const zs407_rf_state_t *next)
{
  if (previous == NULL || next == NULL) {
    return ZS407_RF_DIRTY_ALL;
  }
  uint32_t dirty = 0U;
  if (previous->receiver_hz != next->receiver_hz) {
    dirty |= ZS407_RF_DIRTY_RECEIVER;
  }
  if (previous->local_oscillator_hz != next->local_oscillator_hz) {
    dirty |= ZS407_RF_DIRTY_LOCAL_OSCILLATOR;
  }
  if (previous->attenuation_db_x2 != next->attenuation_db_x2) {
    dirty |= ZS407_RF_DIRTY_ATTENUATOR;
  }
  if (previous->rbw_index != next->rbw_index) {
    dirty |= ZS407_RF_DIRTY_RBW;
  }
  if (previous->path != next->path) {
    dirty |= ZS407_RF_DIRTY_PATH;
  }
  if (previous->output_level_dbm_x10 != next->output_level_dbm_x10) {
    dirty |= ZS407_RF_DIRTY_OUTPUT_LEVEL;
  }
  if (previous->output_enabled != next->output_enabled) {
    dirty |= ZS407_RF_DIRTY_OUTPUT_ENABLE;
  }
  return dirty;
}

zs407_settle_class_t zs407_rf_settle_class(uint32_t dirty_mask)
{
  if ((dirty_mask & ZS407_RF_DIRTY_PATH) != 0U) {
    return ZS407_SETTLE_PATH;
  }
  if ((dirty_mask & ZS407_RF_DIRTY_LOCAL_OSCILLATOR) != 0U) {
    return ZS407_SETTLE_SYNTHESIZER;
  }
  if ((dirty_mask & (ZS407_RF_DIRTY_RECEIVER | ZS407_RF_DIRTY_RBW)) != 0U) {
    return ZS407_SETTLE_RECEIVER;
  }
  if (dirty_mask != 0U) {
    return ZS407_SETTLE_DIGITAL;
  }
  return ZS407_SETTLE_NONE;
}

void zs407_bus_scheduler_init(zs407_bus_scheduler_t *scheduler)
{
  if (scheduler != NULL) {
    scheduler->pending_mask = 0U;
    scheduler->active_client = ZS407_BUS_NONE;
    scheduler->grants = 0U;
  }
}

zs407_core_status_t zs407_bus_request(zs407_bus_scheduler_t *scheduler,
                                      zs407_bus_client_t client)
{
  if (scheduler == NULL || client >= ZS407_BUS_CLIENT_COUNT) {
    return ZS407_CORE_INVALID_ARGUMENT;
  }
  scheduler->pending_mask |= (uint8_t)(1U << (unsigned)client);
  return ZS407_CORE_OK;
}

zs407_bus_client_t zs407_bus_grant_next(zs407_bus_scheduler_t *scheduler)
{
  if (scheduler == NULL || scheduler->active_client != ZS407_BUS_NONE) {
    return ZS407_BUS_NONE;
  }
  for (uint8_t client = 0U; client < ZS407_BUS_CLIENT_COUNT; ++client) {
    uint8_t bit = (uint8_t)(1U << client);
    if ((scheduler->pending_mask & bit) != 0U) {
      scheduler->pending_mask &= (uint8_t)~bit;
      scheduler->active_client = client;
      scheduler->grants++;
      return (zs407_bus_client_t)client;
    }
  }
  return ZS407_BUS_NONE;
}

zs407_core_status_t zs407_bus_release(zs407_bus_scheduler_t *scheduler,
                                      zs407_bus_client_t client)
{
  if (scheduler == NULL || client >= ZS407_BUS_CLIENT_COUNT ||
      scheduler->active_client != (uint8_t)client) {
    return ZS407_CORE_INVALID_ARGUMENT;
  }
  scheduler->active_client = ZS407_BUS_NONE;
  return ZS407_CORE_OK;
}

void zs407_profile_reset(zs407_profile_stats_t *stats)
{
  if (stats != NULL) {
    stats->minimum_cycles = UINT32_MAX;
    stats->maximum_cycles = 0U;
    stats->total_cycles = 0U;
    stats->sample_count = 0U;
  }
}

void zs407_profile_observe(zs407_profile_stats_t *stats, uint32_t cycles)
{
  if (stats == NULL || stats->sample_count == UINT32_MAX) {
    return;
  }
  if (cycles < stats->minimum_cycles) {
    stats->minimum_cycles = cycles;
  }
  if (cycles > stats->maximum_cycles) {
    stats->maximum_cycles = cycles;
  }
  stats->total_cycles += cycles;
  stats->sample_count++;
}

uint32_t zs407_profile_mean(const zs407_profile_stats_t *stats)
{
  if (stats == NULL || stats->sample_count == 0U) {
    return 0U;
  }
  return (uint32_t)(stats->total_cycles / stats->sample_count);
}

uint32_t zs407_services_selftest(void)
{
  uint32_t failures = 0U;
  const zs407_sweep_request_t request = {100U, 110U, 4U};
  const uint64_t expected[] = {100U, 103U, 107U, 110U};
  zs407_frequency_dda_t dda;
  if (zs407_frequency_dda_init(&dda, &request) != ZS407_CORE_OK) {
    failures |= UINT32_C(1) << 0;
  }
  for (size_t i = 0U; i < 4U; ++i) {
    uint64_t frequency = 0U;
    if (!zs407_frequency_dda_next(&dda, &frequency) ||
        frequency != expected[i]) {
      failures |= UINT32_C(1) << 1;
    }
  }

  zs407_rf_state_t a;
  memset(&a, 0, sizeof(a));
  zs407_rf_state_t b = a;
  b.receiver_hz = 1U;
  b.path = ZS407_RF_PATH_ULTRA;
  uint32_t dirty = zs407_rf_state_diff(&a, &b);
  if (dirty != (ZS407_RF_DIRTY_RECEIVER | ZS407_RF_DIRTY_PATH) ||
      zs407_rf_settle_class(dirty) != ZS407_SETTLE_PATH) {
    failures |= UINT32_C(1) << 2;
  }

  zs407_hardware_caps_t caps;
  if (!zs407_hardware_caps(103U, &caps) || !caps.has_max2871 ||
      caps.first_if_hz != 1070100000U ||
      zs407_hardware_caps(0U, &caps)) {
    failures |= UINT32_C(1) << 5;
  }

  zs407_bus_scheduler_t scheduler;
  zs407_bus_scheduler_init(&scheduler);
  (void)zs407_bus_request(&scheduler, ZS407_BUS_DISPLAY);
  (void)zs407_bus_request(&scheduler, ZS407_BUS_RF);
  if (zs407_bus_grant_next(&scheduler) != ZS407_BUS_RF ||
      zs407_bus_release(&scheduler, ZS407_BUS_RF) != ZS407_CORE_OK ||
      zs407_bus_grant_next(&scheduler) != ZS407_BUS_DISPLAY) {
    failures |= UINT32_C(1) << 3;
  }

  zs407_profile_stats_t stats;
  zs407_profile_reset(&stats);
  zs407_profile_observe(&stats, 10U);
  zs407_profile_observe(&stats, 20U);
  if (stats.minimum_cycles != 10U || stats.maximum_cycles != 20U ||
      zs407_profile_mean(&stats) != 15U) {
    failures |= UINT32_C(1) << 4;
  }
  return failures;
}
