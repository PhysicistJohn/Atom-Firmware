/* SPDX-License-Identifier: GPL-3.0-or-later */
#ifndef ZS407_USB_TRANSPORT_H
#define ZS407_USB_TRANSPORT_H

#include "../core/zs407_protocol.h"

typedef struct {
  bool compiled;
  bool running;
  bool hardware_qualified;
  bool shell_ownership_released;
  uint32_t accepted_frames;
  uint32_t rejected_frames;
  uint32_t discarded_bytes;
  uint32_t transmitted_frames;
  uint32_t transport_errors;
} zs407_usb_transport_status_t;

void zs407_usb_transport_status(zs407_usb_transport_status_t *status);
uint32_t zs407_usb_transport_selftest(void);
zs407_core_status_t zs407_usb_transport_start(void);

#endif /* ZS407_USB_TRANSPORT_H */
