/* SPDX-License-Identifier: GPL-3.0-or-later */
#include "zs407_usb_transport.h"

#include "ch.h"
#include "hal.h"
#include "usbcfg.h"

#include "../core/zs407_capabilities.h"
#include "zs407_crc_stm32.h"
#include "../../zs407_features.h"
#if ZS407_FEATURE_PASSIVE_ACQUISITION
#include "zs407_passive_runtime.h"
#endif

#include <string.h>

#define ZS407_RESPONSE_FLAG 0x01U
#define ZS407_ERROR_FLAG 0x02U
#define ZS407_TRANSPORT_THREAD_STACK 640U

static uint8_t transport_frame_storage[ZS407_FRAME_MAX_BYTES]
    __attribute__((aligned(4)));
static zs407_stream_parser_t transport_parser;
static THD_WORKING_AREA(transport_working_area,
                        ZS407_TRANSPORT_THREAD_STACK);
static thread_t *transport_thread;
static volatile bool transport_running;
/* No setters exist in this image. Hardware bring-up must add them explicitly. */
static volatile bool transport_hardware_qualified;
static volatile bool shell_ownership_released;
static volatile uint32_t transmitted_frames;
static volatile uint32_t transport_errors;

static zs407_core_status_t usb_sink(void *context, const uint8_t *data,
                                    size_t length)
{
  BaseSequentialStream *stream = (BaseSequentialStream *)context;
  return streamWrite(stream, data, length) == length
             ? ZS407_CORE_OK
             : ZS407_CORE_BAD_FRAME;
}

static void send_response(const zs407_frame_t *request,
                          uint8_t flags, const zs407_bytes_t *segments,
                          size_t segment_count)
{
  zs407_frame_t response = {
      .version = request->version,
      .flags = flags,
      .request_id = request->request_id,
      .command = request->command,
      .payload = NULL,
      .payload_length = 0U};
  size_t output_length = 0U;
  zs407_core_status_t status = zs407_frame_write_segments(
      &response, segments, segment_count, usb_sink, &SDU1, &output_length);
  (void)output_length;
  if (status == ZS407_CORE_OK) {
    transmitted_frames++;
  } else {
    transport_errors++;
  }
}

static void send_status(const zs407_frame_t *request,
                        zs407_core_status_t status, uint16_t detail)
{
  zs407_status_payload_t payload = {
      .status = (uint8_t)status, .reserved = 0U, .detail = detail};
  uint8_t encoded[ZS407_STATUS_PAYLOAD_BYTES];
  if (!zs407_status_payload_encode(&payload, encoded, sizeof(encoded))) {
    transport_errors++;
    return;
  }
  const zs407_bytes_t segment = {encoded, sizeof(encoded)};
  send_response(request, ZS407_RESPONSE_FLAG | ZS407_ERROR_FLAG,
                &segment, 1U);
}

static void handle_frame(void *context, const zs407_frame_t *request)
{
  (void)context;
  if (request->command == ZS407_COMMAND_PING) {
    const zs407_bytes_t segment = {request->payload, request->payload_length};
    send_response(request, ZS407_RESPONSE_FLAG, &segment, 1U);
    return;
  }
  if (request->command == ZS407_COMMAND_CAPABILITIES &&
      request->payload_length == 0U) {
    zs407_release_manifest_t manifest;
    if (zs407_release_manifest_for_phase(6U, &manifest) != ZS407_CORE_OK) {
      send_status(request, ZS407_CORE_BAD_FRAME, 0U);
      return;
    }
    zs407_capabilities_payload_t payload = {
        .schema_version = ZS407_SCHEMA_VERSION,
        .protocol_version = ZS407_PROTOCOL_VERSION,
        .release_phase = 6U,
        .profile_id = ZS407_RELEASE_PROFILE_ID,
        .feature_bits = manifest.feature_bits,
        .safety_bits = manifest.safety_bits,
        .maximum_payload_bytes = ZS407_PROTOCOL_MAX_PAYLOAD,
        .maximum_trace_points = ZS407_PROTOCOL_MAX_TRACE_POINTS,
        .maximum_sweep_points = manifest.maximum_sweep_points,
        .maximum_fft_points = manifest.maximum_fft_points,
        .waveform_sample_count = manifest.waveform_sample_count,
        .waveform_event_bytes = manifest.waveform_event_bytes};
    uint8_t encoded[ZS407_CAPABILITIES_PAYLOAD_BYTES];
    if (!zs407_capabilities_payload_encode(&payload, encoded,
                                            sizeof(encoded))) {
      send_status(request, ZS407_CORE_BAD_FRAME, 0U);
      return;
    }
    const zs407_bytes_t segment = {encoded, sizeof(encoded)};
    send_response(request, ZS407_RESPONSE_FLAG, &segment, 1U);
    return;
  }
#if ZS407_FEATURE_PASSIVE_ACQUISITION
  if (request->payload_length == 0U &&
      (request->command == ZS407_COMMAND_CLOCK_SNAPSHOT ||
       request->command == ZS407_COMMAND_ACQUISITION_STATUS ||
       request->command == ZS407_COMMAND_ZERO_SPAN_CAPTURE)) {
    zs407_passive_runtime_status_t runtime;
    zs407_passive_runtime_status(&runtime);
    uint8_t encoded[ZS407_CAPTURE_SUMMARY_PAYLOAD_BYTES];
    size_t encoded_length = 0U;
    bool encoded_ok = false;
    if (request->command == ZS407_COMMAND_CLOCK_SNAPSHOT) {
      encoded_length = ZS407_CLOCK_SNAPSHOT_PAYLOAD_BYTES;
      encoded_ok = zs407_clock_snapshot_payload_encode(
          &runtime.clock, encoded, encoded_length);
    } else if (request->command == ZS407_COMMAND_ACQUISITION_STATUS) {
      encoded_length = ZS407_ACQUISITION_STATUS_PAYLOAD_BYTES;
      encoded_ok = zs407_acquisition_status_payload_encode(
          &runtime.acquisition, encoded, encoded_length);
    } else if (runtime.capture_summary_valid) {
      encoded_length = ZS407_CAPTURE_SUMMARY_PAYLOAD_BYTES;
      encoded_ok = zs407_capture_summary_payload_encode(
          &runtime.capture_summary, encoded, encoded_length);
    } else {
      send_status(request, ZS407_CORE_NOT_QUALIFIED, 0U);
      return;
    }
    if (!encoded_ok) {
      send_status(request, ZS407_CORE_BAD_FRAME, 0U);
      return;
    }
    const zs407_bytes_t segment = {encoded, encoded_length};
    send_response(request, ZS407_RESPONSE_FLAG, &segment, 1U);
    return;
  }
#endif
  send_status(request, ZS407_CORE_UNSUPPORTED, request->command);
}

#if ZS407_FEATURE_PASSIVE_ACQUISITION
static void drain_passive_frame(void)
{
  const uint8_t *data = NULL;
  size_t length = 0U;
  if (!zs407_passive_runtime_take_frame(&data, &length)) {
    return;
  }
  if (streamWrite((BaseSequentialStream *)&SDU1, data, length) == length) {
    transmitted_frames++;
  } else {
    transport_errors++;
  }
  zs407_passive_runtime_release_frame();
}
#endif

static THD_FUNCTION(transport_worker, argument)
{
  (void)argument;
  chRegSetThreadName("zs407-binary");
  while (transport_running) {
#if ZS407_FEATURE_PASSIVE_ACQUISITION
    drain_passive_frame();
    msg_t message = ibqGetFullBufferTimeout(&SDU1.ibqueue, MS2ST(10));
    if (message == MSG_TIMEOUT) {
      continue;
    }
#else
    msg_t message = ibqGetFullBufferTimeout(&SDU1.ibqueue, TIME_INFINITE);
#endif
    if (message != MSG_OK) {
      continue;
    }
    uint8_t *data = SDU1.ibqueue.ptr;
    size_t length = (size_t)(SDU1.ibqueue.top - SDU1.ibqueue.ptr);
    size_t accepted = 0U;
    if (zs407_stream_parser_feed(&transport_parser, data, length,
                                 handle_frame, NULL, &accepted) !=
        ZS407_CORE_OK) {
      transport_errors++;
    }
    (void)accepted;
    ibqReleaseEmptyBuffer(&SDU1.ibqueue);
  }
}

typedef struct {
  uint32_t calls;
  zs407_frame_t frame;
  uint8_t payload[8];
} selftest_capture_t;

static void capture_frame(void *context, const zs407_frame_t *frame)
{
  selftest_capture_t *capture = (selftest_capture_t *)context;
  capture->calls++;
  capture->frame = *frame;
  if (frame->payload_length <= sizeof(capture->payload)) {
    memcpy(capture->payload, frame->payload, frame->payload_length);
    capture->frame.payload = capture->payload;
  }
}

uint32_t zs407_usb_transport_selftest(void)
{
  uint32_t failures = 0U;
  uint8_t parser_storage[64];
  uint8_t encoded[64];
  static const uint8_t payload[] = {0x10U, 0x20U, 0x30U, 0x40U};
  zs407_frame_t input = {
      .version = ZS407_PROTOCOL_VERSION,
      .flags = 0x5aU,
      .request_id = 407U,
      .command = ZS407_COMMAND_PING,
      .payload = payload,
      .payload_length = sizeof(payload)};
  size_t encoded_length = 0U;
  zs407_stream_parser_t parser;
  selftest_capture_t capture = {0};
  if (zs407_stream_parser_init(&parser, parser_storage,
                               sizeof(parser_storage)) != ZS407_CORE_OK ||
      zs407_frame_encode(&input, encoded, sizeof(encoded),
                         &encoded_length) != ZS407_CORE_OK) {
    failures |= 1U;
  } else {
    for (size_t offset = 0U; offset < encoded_length;) {
      size_t count = (offset % 5U) + 1U;
      if (count > encoded_length - offset) {
        count = encoded_length - offset;
      }
      size_t accepted = 0U;
      if (zs407_stream_parser_feed(&parser, &encoded[offset], count,
                                   capture_frame, &capture, &accepted) !=
          ZS407_CORE_OK) {
        failures |= 2U;
      }
      offset += count;
    }
  }
  if (capture.calls != 1U || capture.frame.request_id != 407U ||
      capture.frame.payload_length != sizeof(payload) ||
      memcmp(capture.frame.payload, payload, sizeof(payload)) != 0) {
    failures |= 4U;
  }
  failures |= zs407_crc32_stm32_selftest() << 4;
  return failures;
}

zs407_core_status_t zs407_usb_transport_start(void)
{
  if (transport_running) {
    return ZS407_CORE_OK;
  }
  if (!transport_hardware_qualified || !shell_ownership_released) {
    return ZS407_CORE_NOT_QUALIFIED;
  }
  if (zs407_stream_parser_init(&transport_parser, transport_frame_storage,
                               sizeof(transport_frame_storage)) !=
      ZS407_CORE_OK) {
    return ZS407_CORE_BAD_FRAME;
  }
  transport_running = true;
  transport_thread = chThdCreateStatic(
      transport_working_area, sizeof(transport_working_area),
      NORMALPRIO + 1, transport_worker, NULL);
  if (transport_thread == NULL) {
    transport_running = false;
    return ZS407_CORE_BAD_FRAME;
  }
  return ZS407_CORE_OK;
}

void zs407_usb_transport_status(zs407_usb_transport_status_t *status)
{
  if (status != NULL) {
    status->compiled = true;
    status->running = transport_running;
    status->hardware_qualified = transport_hardware_qualified;
    status->shell_ownership_released = shell_ownership_released;
    status->accepted_frames = transport_parser.accepted_frames;
    status->rejected_frames = transport_parser.rejected_frames;
    status->discarded_bytes = transport_parser.discarded_bytes;
    status->transmitted_frames = transmitted_frames;
    status->transport_errors = transport_errors;
  }
}
