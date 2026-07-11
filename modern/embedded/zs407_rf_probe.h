/* SPDX-License-Identifier: GPL-3.0-or-later */
#ifndef ZS407_RF_PROBE_H
#define ZS407_RF_PROBE_H

#include <stdint.h>

typedef struct {
  uint8_t frr_mode[4];
  uint8_t frr_value[4];
  uint8_t rssi_control;
  uint8_t rssi_compensation;
  uint8_t fast_rssi_delay;
  uint32_t elapsed_cycles;
} zs407_si4468_probe_t;

/* GET_PROPERTY and FRR reads only; no radio property is changed. */
int zs407_si4468_probe(zs407_si4468_probe_t *probe);

#endif /* ZS407_RF_PROBE_H */
