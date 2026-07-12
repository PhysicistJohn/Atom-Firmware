/* SPDX-License-Identifier: GPL-3.0-or-later */
#include "zs407_transport_lifecycle.h"

#include <string.h>

_Static_assert(sizeof(zs407_transport_lifecycle_t) == 32U,
               "transport lifecycle layout changed");

static uint32_t load_u32(const uint32_t *value)
{
  return __atomic_load_n(value, __ATOMIC_ACQUIRE);
}

static void store_u32(uint32_t *value, uint32_t next)
{
  __atomic_store_n(value, next, __ATOMIC_RELEASE);
}

static void increment_u32(uint32_t *value)
{
  uint32_t current = load_u32(value);
  while (current != UINT32_MAX &&
         !__atomic_compare_exchange_n(value, &current, current + 1U,
                                      false, __ATOMIC_ACQ_REL,
                                      __ATOMIC_ACQUIRE)) {
  }
}

static bool transition(zs407_transport_lifecycle_t *lifecycle,
                       uint32_t expected, uint32_t next)
{
  return __atomic_compare_exchange_n(&lifecycle->state, &expected, next,
                                     false, __ATOMIC_ACQ_REL,
                                     __ATOMIC_ACQUIRE);
}

void zs407_transport_lifecycle_init(
    zs407_transport_lifecycle_t *lifecycle, bool qualification_enabled)
{
  if (lifecycle == NULL) {
    return;
  }
  memset(lifecycle, 0, sizeof(*lifecycle));
  store_u32(&lifecycle->qualification_enabled,
            qualification_enabled ? 1U : 0U);
  store_u32(&lifecycle->state,
            qualification_enabled ? ZS407_TRANSPORT_SHELL_READY
                                  : ZS407_TRANSPORT_SHELL_LOCKED);
}

zs407_core_status_t zs407_transport_lifecycle_request(
    zs407_transport_lifecycle_t *lifecycle)
{
  if (lifecycle == NULL) {
    return ZS407_CORE_INVALID_ARGUMENT;
  }
  increment_u32(&lifecycle->request_attempts);
  if (load_u32(&lifecycle->qualification_enabled) == 0U ||
      load_u32(&lifecycle->one_shot_used) != 0U) {
    return ZS407_CORE_NOT_QUALIFIED;
  }
  if (!transition(lifecycle, ZS407_TRANSPORT_SHELL_READY,
                  ZS407_TRANSPORT_HANDOFF_REQUESTED)) {
    return ZS407_CORE_OUT_OF_RANGE;
  }
  store_u32(&lifecycle->one_shot_used, 1U);
  increment_u32(&lifecycle->accepted_handoffs);
  return ZS407_CORE_OK;
}

zs407_core_status_t zs407_transport_lifecycle_begin(
    zs407_transport_lifecycle_t *lifecycle)
{
  if (lifecycle == NULL) {
    return ZS407_CORE_INVALID_ARGUMENT;
  }
  return transition(lifecycle, ZS407_TRANSPORT_HANDOFF_REQUESTED,
                    ZS407_TRANSPORT_STARTING)
             ? ZS407_CORE_OK
             : ZS407_CORE_OUT_OF_RANGE;
}

zs407_core_status_t zs407_transport_lifecycle_activate(
    zs407_transport_lifecycle_t *lifecycle)
{
  if (lifecycle == NULL) {
    return ZS407_CORE_INVALID_ARGUMENT;
  }
  if (!transition(lifecycle, ZS407_TRANSPORT_STARTING,
                  ZS407_TRANSPORT_BINARY_ACTIVE)) {
    return ZS407_CORE_OUT_OF_RANGE;
  }
  increment_u32(&lifecycle->starts);
  return ZS407_CORE_OK;
}

zs407_core_status_t zs407_transport_lifecycle_fail(
    zs407_transport_lifecycle_t *lifecycle)
{
  if (lifecycle == NULL) {
    return ZS407_CORE_INVALID_ARGUMENT;
  }
  uint32_t state = load_u32(&lifecycle->state);
  while (state == ZS407_TRANSPORT_HANDOFF_REQUESTED ||
         state == ZS407_TRANSPORT_STARTING ||
         state == ZS407_TRANSPORT_BINARY_ACTIVE) {
    if (__atomic_compare_exchange_n(&lifecycle->state, &state,
                                    ZS407_TRANSPORT_FAILED, false,
                                    __ATOMIC_ACQ_REL, __ATOMIC_ACQUIRE)) {
      increment_u32(&lifecycle->failures);
      return ZS407_CORE_OK;
    }
  }
  return ZS407_CORE_OUT_OF_RANGE;
}

zs407_core_status_t zs407_transport_lifecycle_disconnect(
    zs407_transport_lifecycle_t *lifecycle)
{
  if (lifecycle == NULL) {
    return ZS407_CORE_INVALID_ARGUMENT;
  }
  if (!transition(lifecycle, ZS407_TRANSPORT_BINARY_ACTIVE,
                  ZS407_TRANSPORT_SHELL_RECOVERED)) {
    return ZS407_CORE_OUT_OF_RANGE;
  }
  increment_u32(&lifecycle->recoveries);
  return ZS407_CORE_OK;
}

void zs407_transport_lifecycle_snapshot(
    const zs407_transport_lifecycle_t *lifecycle,
    zs407_transport_lifecycle_snapshot_t *snapshot)
{
  if (snapshot == NULL) {
    return;
  }
  memset(snapshot, 0, sizeof(*snapshot));
  if (lifecycle == NULL) {
    return;
  }
  snapshot->state = load_u32(&lifecycle->state);
  snapshot->qualification_enabled =
      load_u32(&lifecycle->qualification_enabled);
  snapshot->one_shot_used = load_u32(&lifecycle->one_shot_used);
  snapshot->request_attempts = load_u32(&lifecycle->request_attempts);
  snapshot->accepted_handoffs = load_u32(&lifecycle->accepted_handoffs);
  snapshot->starts = load_u32(&lifecycle->starts);
  snapshot->recoveries = load_u32(&lifecycle->recoveries);
  snapshot->failures = load_u32(&lifecycle->failures);
}

bool zs407_transport_lifecycle_handoff_requested(
    const zs407_transport_lifecycle_t *lifecycle)
{
  return lifecycle != NULL &&
         load_u32(&lifecycle->state) ==
             ZS407_TRANSPORT_HANDOFF_REQUESTED;
}

bool zs407_transport_lifecycle_binary_active(
    const zs407_transport_lifecycle_t *lifecycle)
{
  return lifecycle != NULL &&
         load_u32(&lifecycle->state) == ZS407_TRANSPORT_BINARY_ACTIVE;
}

bool zs407_transport_lifecycle_shell_may_spawn(
    const zs407_transport_lifecycle_t *lifecycle)
{
  if (lifecycle == NULL) {
    return true;
  }
  uint32_t state = load_u32(&lifecycle->state);
  return state == ZS407_TRANSPORT_SHELL_LOCKED ||
         state == ZS407_TRANSPORT_SHELL_READY ||
         state == ZS407_TRANSPORT_SHELL_RECOVERED ||
         state == ZS407_TRANSPORT_FAILED;
}

uint32_t zs407_transport_lifecycle_selftest(void)
{
  uint32_t failures = 0U;
  zs407_transport_lifecycle_t lifecycle;
  zs407_transport_lifecycle_snapshot_t snapshot;

  zs407_transport_lifecycle_init(&lifecycle, false);
  if (!zs407_transport_lifecycle_shell_may_spawn(&lifecycle) ||
      zs407_transport_lifecycle_request(&lifecycle) !=
          ZS407_CORE_NOT_QUALIFIED) {
    failures |= UINT32_C(1) << 0;
  }

  zs407_transport_lifecycle_init(&lifecycle, true);
  if (!zs407_transport_lifecycle_shell_may_spawn(&lifecycle) ||
      zs407_transport_lifecycle_begin(&lifecycle) !=
          ZS407_CORE_OUT_OF_RANGE ||
      zs407_transport_lifecycle_request(&lifecycle) != ZS407_CORE_OK ||
      !zs407_transport_lifecycle_handoff_requested(&lifecycle) ||
      zs407_transport_lifecycle_shell_may_spawn(&lifecycle)) {
    failures |= UINT32_C(1) << 1;
  }
  if (zs407_transport_lifecycle_request(&lifecycle) !=
          ZS407_CORE_NOT_QUALIFIED ||
      zs407_transport_lifecycle_begin(&lifecycle) != ZS407_CORE_OK ||
      zs407_transport_lifecycle_activate(&lifecycle) != ZS407_CORE_OK ||
      !zs407_transport_lifecycle_binary_active(&lifecycle)) {
    failures |= UINT32_C(1) << 2;
  }
  if (zs407_transport_lifecycle_disconnect(&lifecycle) != ZS407_CORE_OK ||
      !zs407_transport_lifecycle_shell_may_spawn(&lifecycle) ||
      zs407_transport_lifecycle_request(&lifecycle) !=
          ZS407_CORE_NOT_QUALIFIED) {
    failures |= UINT32_C(1) << 3;
  }
  zs407_transport_lifecycle_snapshot(&lifecycle, &snapshot);
  if (snapshot.state != ZS407_TRANSPORT_SHELL_RECOVERED ||
      snapshot.qualification_enabled != 1U ||
      snapshot.one_shot_used != 1U || snapshot.request_attempts != 3U ||
      snapshot.accepted_handoffs != 1U || snapshot.starts != 1U ||
      snapshot.recoveries != 1U || snapshot.failures != 0U) {
    failures |= UINT32_C(1) << 4;
  }

  zs407_transport_lifecycle_init(&lifecycle, true);
  if (zs407_transport_lifecycle_request(&lifecycle) != ZS407_CORE_OK ||
      zs407_transport_lifecycle_begin(&lifecycle) != ZS407_CORE_OK ||
      zs407_transport_lifecycle_fail(&lifecycle) != ZS407_CORE_OK ||
      !zs407_transport_lifecycle_shell_may_spawn(&lifecycle) ||
      zs407_transport_lifecycle_request(&lifecycle) !=
          ZS407_CORE_NOT_QUALIFIED ||
      zs407_transport_lifecycle_disconnect(&lifecycle) !=
          ZS407_CORE_OUT_OF_RANGE) {
    failures |= UINT32_C(1) << 5;
  }
  zs407_transport_lifecycle_snapshot(&lifecycle, &snapshot);
  if (snapshot.state != ZS407_TRANSPORT_FAILED ||
      snapshot.accepted_handoffs != 1U || snapshot.starts != 0U ||
      snapshot.recoveries != 0U || snapshot.failures != 1U) {
    failures |= UINT32_C(1) << 6;
  }
  return failures;
}
