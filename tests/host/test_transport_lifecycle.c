/* SPDX-License-Identifier: GPL-3.0-or-later */
#include "modern/core/zs407_transport_lifecycle.h"

#include <pthread.h>
#include <stdio.h>
#include <stdlib.h>

#define CHECK(condition)                                                       \
  do {                                                                         \
    if (!(condition)) {                                                        \
      fprintf(stderr, "CHECK failed at %s:%d: %s\n", __FILE__, __LINE__,      \
              #condition);                                                     \
      return 1;                                                                \
    }                                                                          \
  } while (0)

#define REQUEST_THREADS 32U

typedef struct {
  zs407_transport_lifecycle_t *lifecycle;
  uint32_t *ready;
  uint32_t *go;
  zs407_core_status_t result;
} request_context_t;

static void *request_worker(void *argument)
{
  request_context_t *context = (request_context_t *)argument;
  __atomic_fetch_add(context->ready, 1U, __ATOMIC_ACQ_REL);
  while (__atomic_load_n(context->go, __ATOMIC_ACQUIRE) == 0U) {
  }
  context->result = zs407_transport_lifecycle_request(context->lifecycle);
  return NULL;
}

static int test_concurrent_request(void)
{
  zs407_transport_lifecycle_t lifecycle;
  zs407_transport_lifecycle_init(&lifecycle, true);
  pthread_t threads[REQUEST_THREADS];
  request_context_t contexts[REQUEST_THREADS];
  uint32_t ready = 0U;
  uint32_t go = 0U;
  for (size_t i = 0U; i < REQUEST_THREADS; ++i) {
    contexts[i] = (request_context_t){
        .lifecycle = &lifecycle, .ready = &ready, .go = &go,
        .result = ZS407_CORE_BAD_FRAME};
    CHECK(pthread_create(&threads[i], NULL, request_worker, &contexts[i]) == 0);
  }
  while (__atomic_load_n(&ready, __ATOMIC_ACQUIRE) != REQUEST_THREADS) {
  }
  __atomic_store_n(&go, 1U, __ATOMIC_RELEASE);
  size_t accepted = 0U;
  for (size_t i = 0U; i < REQUEST_THREADS; ++i) {
    CHECK(pthread_join(threads[i], NULL) == 0);
    if (contexts[i].result == ZS407_CORE_OK) {
      accepted++;
    } else {
      CHECK(contexts[i].result == ZS407_CORE_NOT_QUALIFIED ||
            contexts[i].result == ZS407_CORE_OUT_OF_RANGE);
    }
  }
  CHECK(accepted == 1U);
  zs407_transport_lifecycle_snapshot_t snapshot;
  zs407_transport_lifecycle_snapshot(&lifecycle, &snapshot);
  CHECK(snapshot.state == ZS407_TRANSPORT_HANDOFF_REQUESTED);
  CHECK(snapshot.request_attempts == REQUEST_THREADS);
  CHECK(snapshot.accepted_handoffs == 1U);
  CHECK(snapshot.one_shot_used == 1U);
  CHECK(zs407_transport_lifecycle_begin(&lifecycle) == ZS407_CORE_OK);
  CHECK(zs407_transport_lifecycle_activate(&lifecycle) == ZS407_CORE_OK);
  CHECK(zs407_transport_lifecycle_disconnect(&lifecycle) == ZS407_CORE_OK);
  return 0;
}

static uint32_t random_state = UINT32_C(0x40705a5a);

static uint32_t next_random(void)
{
  random_state ^= random_state << 13;
  random_state ^= random_state >> 17;
  random_state ^= random_state << 5;
  return random_state;
}

static int validate_snapshot(const zs407_transport_lifecycle_t *lifecycle)
{
  zs407_transport_lifecycle_snapshot_t snapshot;
  zs407_transport_lifecycle_snapshot(lifecycle, &snapshot);
  CHECK(snapshot.state <= ZS407_TRANSPORT_FAILED);
  CHECK(snapshot.qualification_enabled <= 1U);
  CHECK(snapshot.one_shot_used <= 1U);
  CHECK(snapshot.accepted_handoffs <= 1U);
  CHECK(snapshot.accepted_handoffs == snapshot.one_shot_used);
  CHECK(snapshot.starts <= snapshot.accepted_handoffs);
  CHECK(snapshot.recoveries <= snapshot.starts);
  CHECK(snapshot.failures <= snapshot.accepted_handoffs);
  CHECK(snapshot.recoveries + snapshot.failures <= 1U);
  CHECK(zs407_transport_lifecycle_handoff_requested(lifecycle) ==
        (snapshot.state == ZS407_TRANSPORT_HANDOFF_REQUESTED));
  CHECK(zs407_transport_lifecycle_binary_active(lifecycle) ==
        (snapshot.state == ZS407_TRANSPORT_BINARY_ACTIVE));
  bool expected_shell = snapshot.state == ZS407_TRANSPORT_SHELL_LOCKED ||
                        snapshot.state == ZS407_TRANSPORT_SHELL_READY ||
                        snapshot.state == ZS407_TRANSPORT_SHELL_RECOVERED ||
                        snapshot.state == ZS407_TRANSPORT_FAILED;
  CHECK(zs407_transport_lifecycle_shell_may_spawn(lifecycle) == expected_shell);
  if (snapshot.qualification_enabled == 0U) {
    CHECK(snapshot.state == ZS407_TRANSPORT_SHELL_LOCKED);
    CHECK(snapshot.accepted_handoffs == 0U);
  }
  return 0;
}

static int test_mutation_sequences(void)
{
  for (size_t iteration = 0U; iteration < 100000U; ++iteration) {
    zs407_transport_lifecycle_t lifecycle;
    zs407_transport_lifecycle_init(&lifecycle,
                                   (next_random() & 1U) != 0U);
    for (size_t event = 0U; event < 10U; ++event) {
      switch (next_random() % 5U) {
      case 0U:
        (void)zs407_transport_lifecycle_request(&lifecycle);
        break;
      case 1U:
        (void)zs407_transport_lifecycle_begin(&lifecycle);
        break;
      case 2U:
        (void)zs407_transport_lifecycle_activate(&lifecycle);
        break;
      case 3U:
        (void)zs407_transport_lifecycle_fail(&lifecycle);
        break;
      default:
        (void)zs407_transport_lifecycle_disconnect(&lifecycle);
        break;
      }
      CHECK(validate_snapshot(&lifecycle) == 0);
    }
  }
  return 0;
}

int main(void)
{
  CHECK(zs407_transport_lifecycle_selftest() == 0U);
  CHECK(zs407_transport_lifecycle_request(NULL) ==
        ZS407_CORE_INVALID_ARGUMENT);
  CHECK(zs407_transport_lifecycle_begin(NULL) ==
        ZS407_CORE_INVALID_ARGUMENT);
  CHECK(zs407_transport_lifecycle_activate(NULL) ==
        ZS407_CORE_INVALID_ARGUMENT);
  CHECK(zs407_transport_lifecycle_fail(NULL) ==
        ZS407_CORE_INVALID_ARGUMENT);
  CHECK(zs407_transport_lifecycle_disconnect(NULL) ==
        ZS407_CORE_INVALID_ARGUMENT);
  CHECK(zs407_transport_lifecycle_shell_may_spawn(NULL));
  CHECK(!zs407_transport_lifecycle_binary_active(NULL));
  CHECK(!zs407_transport_lifecycle_handoff_requested(NULL));
  CHECK(test_concurrent_request() == 0);
  CHECK(test_mutation_sequences() == 0);
  puts("ZS407 transport lifecycle: 1000000 transitions and concurrency passed");
  return 0;
}
