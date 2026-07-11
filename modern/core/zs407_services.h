/* SPDX-License-Identifier: GPL-3.0-or-later */
#ifndef ZS407_SERVICES_H
#define ZS407_SERVICES_H

#include "zs407_core.h"

typedef enum {
  ZS407_RF_PATH_LOW = 0,
  ZS407_RF_PATH_DIRECT = 1,
  ZS407_RF_PATH_ULTRA = 2,
  ZS407_RF_PATH_LEAKAGE = 3
} zs407_rf_path_t;

typedef struct {
  uint64_t receiver_hz;
  uint64_t local_oscillator_hz;
  int16_t attenuation_db_x2;
  int16_t output_level_dbm_x10;
  uint8_t rbw_index;
  uint8_t path;
  bool output_enabled;
} zs407_rf_state_t;

enum {
  ZS407_RF_DIRTY_RECEIVER = UINT32_C(1) << 0,
  ZS407_RF_DIRTY_LOCAL_OSCILLATOR = UINT32_C(1) << 1,
  ZS407_RF_DIRTY_ATTENUATOR = UINT32_C(1) << 2,
  ZS407_RF_DIRTY_RBW = UINT32_C(1) << 3,
  ZS407_RF_DIRTY_PATH = UINT32_C(1) << 4,
  ZS407_RF_DIRTY_OUTPUT_LEVEL = UINT32_C(1) << 5,
  ZS407_RF_DIRTY_OUTPUT_ENABLE = UINT32_C(1) << 6,
  ZS407_RF_DIRTY_ALL = (UINT32_C(1) << 7) - 1U
};

typedef enum {
  ZS407_SETTLE_NONE = 0,
  ZS407_SETTLE_DIGITAL = 1,
  ZS407_SETTLE_RECEIVER = 2,
  ZS407_SETTLE_SYNTHESIZER = 3,
  ZS407_SETTLE_PATH = 4
} zs407_settle_class_t;

typedef struct {
  uint16_t hardware_id;
  uint32_t first_if_hz;
  uint32_t normal_input_max_hz;
  uint64_t synthesized_limit_hz;
  bool has_plus_if;
  bool has_max2871;
} zs407_hardware_caps_t;

bool zs407_hardware_caps(uint16_t hardware_id, zs407_hardware_caps_t *caps);

uint32_t zs407_rf_state_diff(const zs407_rf_state_t *previous,
                             const zs407_rf_state_t *next);
zs407_settle_class_t zs407_rf_settle_class(uint32_t dirty_mask);

typedef enum {
  ZS407_BUS_RF = 0,
  ZS407_BUS_CONTROL = 1,
  ZS407_BUS_DISPLAY = 2,
  ZS407_BUS_STORAGE = 3,
  ZS407_BUS_CLIENT_COUNT = 4,
  ZS407_BUS_NONE = 255
} zs407_bus_client_t;

typedef struct {
  uint8_t pending_mask;
  uint8_t active_client;
  uint32_t grants;
} zs407_bus_scheduler_t;

void zs407_bus_scheduler_init(zs407_bus_scheduler_t *scheduler);
zs407_core_status_t zs407_bus_request(zs407_bus_scheduler_t *scheduler,
                                      zs407_bus_client_t client);
zs407_bus_client_t zs407_bus_grant_next(zs407_bus_scheduler_t *scheduler);
zs407_core_status_t zs407_bus_release(zs407_bus_scheduler_t *scheduler,
                                      zs407_bus_client_t client);

typedef struct {
  uint32_t minimum_cycles;
  uint32_t maximum_cycles;
  uint64_t total_cycles;
  uint32_t sample_count;
} zs407_profile_stats_t;

void zs407_profile_reset(zs407_profile_stats_t *stats);
void zs407_profile_observe(zs407_profile_stats_t *stats, uint32_t cycles);
uint32_t zs407_profile_mean(const zs407_profile_stats_t *stats);

/* A deterministic, hardware-free smoke test suitable for the shell. */
uint32_t zs407_services_selftest(void);

#endif /* ZS407_SERVICES_H */
