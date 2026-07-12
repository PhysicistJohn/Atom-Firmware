/* SPDX-License-Identifier: GPL-3.0-or-later */
#ifndef ZS407_TRANSPORT_LIFECYCLE_H
#define ZS407_TRANSPORT_LIFECYCLE_H

#include "zs407_core.h"

typedef enum {
  ZS407_TRANSPORT_SHELL_LOCKED = 0,
  ZS407_TRANSPORT_SHELL_READY = 1,
  ZS407_TRANSPORT_HANDOFF_REQUESTED = 2,
  ZS407_TRANSPORT_STARTING = 3,
  ZS407_TRANSPORT_BINARY_ACTIVE = 4,
  ZS407_TRANSPORT_SHELL_RECOVERED = 5,
  ZS407_TRANSPORT_FAILED = 6
} zs407_transport_lifecycle_state_t;

/*
 * All fields are 32-bit so the embedded executable twin can inspect the
 * lifecycle without relying on compiler-specific bool or enum layout.
 * Access after init is through the atomic helpers in the implementation.
 */
typedef struct {
  uint32_t state;
  uint32_t qualification_enabled;
  uint32_t one_shot_used;
  uint32_t request_attempts;
  uint32_t accepted_handoffs;
  uint32_t starts;
  uint32_t recoveries;
  uint32_t failures;
} zs407_transport_lifecycle_t;

typedef struct {
  uint32_t state;
  uint32_t qualification_enabled;
  uint32_t one_shot_used;
  uint32_t request_attempts;
  uint32_t accepted_handoffs;
  uint32_t starts;
  uint32_t recoveries;
  uint32_t failures;
} zs407_transport_lifecycle_snapshot_t;

void zs407_transport_lifecycle_init(
    zs407_transport_lifecycle_t *lifecycle, bool qualification_enabled);
zs407_core_status_t zs407_transport_lifecycle_request(
    zs407_transport_lifecycle_t *lifecycle);
zs407_core_status_t zs407_transport_lifecycle_begin(
    zs407_transport_lifecycle_t *lifecycle);
zs407_core_status_t zs407_transport_lifecycle_activate(
    zs407_transport_lifecycle_t *lifecycle);
zs407_core_status_t zs407_transport_lifecycle_fail(
    zs407_transport_lifecycle_t *lifecycle);
zs407_core_status_t zs407_transport_lifecycle_disconnect(
    zs407_transport_lifecycle_t *lifecycle);
void zs407_transport_lifecycle_snapshot(
    const zs407_transport_lifecycle_t *lifecycle,
    zs407_transport_lifecycle_snapshot_t *snapshot);
bool zs407_transport_lifecycle_handoff_requested(
    const zs407_transport_lifecycle_t *lifecycle);
bool zs407_transport_lifecycle_binary_active(
    const zs407_transport_lifecycle_t *lifecycle);
bool zs407_transport_lifecycle_shell_may_spawn(
    const zs407_transport_lifecycle_t *lifecycle);
uint32_t zs407_transport_lifecycle_selftest(void);

#endif /* ZS407_TRANSPORT_LIFECYCLE_H */
