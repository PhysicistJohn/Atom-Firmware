/* SPDX-License-Identifier: GPL-3.0-or-later */
#ifndef ZS407_USB_TRANSPORT_H
#define ZS407_USB_TRANSPORT_H

#include "../core/zs407_protocol.h"
#include "../core/zs407_transport_lifecycle.h"

typedef struct {
  bool compiled;
  bool running;
  bool qualification_build;
  bool admission_enabled;
  bool hardware_qualified;
  bool shell_ownership_released;
  bool worker_present;
  uint32_t lifecycle_state;
  uint32_t one_shot_used;
  uint32_t request_attempts;
  uint32_t accepted_handoffs;
  uint32_t starts;
  uint32_t recoveries;
  uint32_t failures;
  uint32_t accepted_frames;
  uint32_t rejected_frames;
  uint32_t discarded_bytes;
  uint32_t transmitted_frames;
  uint32_t transport_errors;
} zs407_usb_transport_status_t;

void zs407_usb_transport_init(void);
void zs407_usb_transport_status(zs407_usb_transport_status_t *status);
uint32_t zs407_usb_transport_selftest(void);
/* Requests a handoff; it never starts a worker in the calling sweep thread. */
zs407_core_status_t zs407_usb_transport_start(void);
/* Called only by the shell thread after its final ASCII prompt is queued. */
zs407_core_status_t zs407_usb_transport_complete_handoff(void);
bool zs407_usb_transport_handoff_requested(void);
bool zs407_usb_transport_shell_may_spawn(void);

#endif /* ZS407_USB_TRANSPORT_H */
