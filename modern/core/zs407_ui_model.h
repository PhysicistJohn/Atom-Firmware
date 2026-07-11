/* SPDX-License-Identifier: GPL-3.0-or-later */
#ifndef ZS407_UI_MODEL_H
#define ZS407_UI_MODEL_H

#include "zs407_core.h"

#define ZS407_UI_WIDTH 480U
#define ZS407_UI_HEIGHT 320U
#define ZS407_UI_TILE_SIZE 32U
#define ZS407_UI_TILE_COLUMNS 15U
#define ZS407_UI_TILE_ROWS 10U
#define ZS407_UI_TILE_COUNT 150U
#define ZS407_UI_TILE_WORDS 5U

typedef struct {
  uint32_t words[ZS407_UI_TILE_WORDS];
} zs407_dirty_tiles_t;

typedef struct {
  uint32_t sequence;
  uint64_t start_hz;
  uint64_t stop_hz;
  uint32_t actual_rbw_hz_x10;
  uint32_t elapsed_us;
  uint16_t point_count;
  uint16_t acquired_points;
  uint32_t flags;
} zs407_ui_snapshot_t;

void zs407_dirty_tiles_clear(zs407_dirty_tiles_t *tiles);
void zs407_dirty_tiles_all(zs407_dirty_tiles_t *tiles);
void zs407_dirty_tiles_invalidate(zs407_dirty_tiles_t *tiles,
                                  int16_t x, int16_t y,
                                  int16_t width, int16_t height);
bool zs407_dirty_tiles_pop(zs407_dirty_tiles_t *tiles, uint16_t *tile_index);

zs407_core_status_t zs407_trace_envelope(
    const zs407_db32_t *samples, size_t sample_count, size_t columns,
    zs407_db32_t *minimum, zs407_db32_t *maximum);
uint32_t zs407_ui_model_selftest(void);

#endif /* ZS407_UI_MODEL_H */
