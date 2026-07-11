/* SPDX-License-Identifier: GPL-3.0-or-later */
#include "zs407_ui_model.h"

#include <string.h>

void zs407_dirty_tiles_clear(zs407_dirty_tiles_t *tiles)
{
  if (tiles != NULL) {
    memset(tiles, 0, sizeof(*tiles));
  }
}

void zs407_dirty_tiles_all(zs407_dirty_tiles_t *tiles)
{
  if (tiles == NULL) {
    return;
  }
  for (size_t word = 0U; word < ZS407_UI_TILE_WORDS; ++word) {
    tiles->words[word] = UINT32_MAX;
  }
  tiles->words[ZS407_UI_TILE_WORDS - 1U] &=
      (UINT32_C(1) << (ZS407_UI_TILE_COUNT % 32U)) - 1U;
}

void zs407_dirty_tiles_invalidate(zs407_dirty_tiles_t *tiles,
                                  int16_t x, int16_t y,
                                  int16_t width, int16_t height)
{
  if (tiles == NULL || width <= 0 || height <= 0 ||
      (int32_t)x >= (int32_t)ZS407_UI_WIDTH ||
      (int32_t)y >= (int32_t)ZS407_UI_HEIGHT ||
      (int32_t)x + width <= 0 || (int32_t)y + height <= 0) {
    return;
  }
  int32_t left = x < 0 ? 0 : x;
  int32_t top = y < 0 ? 0 : y;
  int32_t right = (int32_t)x + width;
  int32_t bottom = (int32_t)y + height;
  if (right > (int32_t)ZS407_UI_WIDTH) {
    right = ZS407_UI_WIDTH;
  }
  if (bottom > (int32_t)ZS407_UI_HEIGHT) {
    bottom = ZS407_UI_HEIGHT;
  }
  unsigned first_column = (unsigned)left / ZS407_UI_TILE_SIZE;
  unsigned last_column = (unsigned)(right - 1) / ZS407_UI_TILE_SIZE;
  unsigned first_row = (unsigned)top / ZS407_UI_TILE_SIZE;
  unsigned last_row = (unsigned)(bottom - 1) / ZS407_UI_TILE_SIZE;
  for (unsigned row = first_row; row <= last_row; ++row) {
    for (unsigned column = first_column; column <= last_column; ++column) {
      unsigned index = row * ZS407_UI_TILE_COLUMNS + column;
      tiles->words[index / 32U] |= UINT32_C(1) << (index % 32U);
    }
  }
}

bool zs407_dirty_tiles_pop(zs407_dirty_tiles_t *tiles, uint16_t *tile_index)
{
  if (tiles == NULL || tile_index == NULL) {
    return false;
  }
  for (unsigned word = 0U; word < ZS407_UI_TILE_WORDS; ++word) {
    if (tiles->words[word] != 0U) {
      unsigned bit = 0U;
      while ((tiles->words[word] & (UINT32_C(1) << bit)) == 0U) {
        ++bit;
      }
      tiles->words[word] &= ~(UINT32_C(1) << bit);
      *tile_index = (uint16_t)(word * 32U + bit);
      return *tile_index < ZS407_UI_TILE_COUNT;
    }
  }
  return false;
}

zs407_core_status_t zs407_trace_envelope(
    const zs407_db32_t *samples, size_t sample_count, size_t columns,
    zs407_db32_t *minimum, zs407_db32_t *maximum)
{
  if (samples == NULL || minimum == NULL || maximum == NULL ||
      sample_count == 0U || columns == 0U) {
    return ZS407_CORE_INVALID_ARGUMENT;
  }
  for (size_t column = 0U; column < columns; ++column) {
    size_t first = (column * sample_count) / columns;
    size_t last = ((column + 1U) * sample_count + columns - 1U) / columns;
    if (first >= sample_count) {
      first = sample_count - 1U;
    }
    if (last <= first) {
      last = first + 1U;
    }
    if (last > sample_count) {
      last = sample_count;
    }
    zs407_db32_t low = ZS407_TRACE_INVALID_SAMPLE;
    zs407_db32_t high = ZS407_TRACE_INVALID_SAMPLE;
    for (size_t index = first; index < last; ++index) {
      if (samples[index] == ZS407_TRACE_INVALID_SAMPLE) {
        continue;
      }
      if (low == ZS407_TRACE_INVALID_SAMPLE) {
        low = samples[index];
        high = samples[index];
        continue;
      }
      if (samples[index] < low) {
        low = samples[index];
      }
      if (samples[index] > high) {
        high = samples[index];
      }
    }
    minimum[column] = low;
    maximum[column] = high;
  }
  return ZS407_CORE_OK;
}

uint32_t zs407_ui_model_selftest(void)
{
  zs407_dirty_tiles_t tiles;
  zs407_dirty_tiles_clear(&tiles);
  zs407_dirty_tiles_invalidate(&tiles, 31, 31, 2, 2);
  const uint16_t expected[] = {0U, 1U, 15U, 16U};
  for (size_t i = 0U; i < 4U; ++i) {
    uint16_t tile = 0U;
    if (!zs407_dirty_tiles_pop(&tiles, &tile) || tile != expected[i]) {
      return UINT32_C(1) << 0;
    }
  }
  uint16_t tile = 0U;
  if (zs407_dirty_tiles_pop(&tiles, &tile)) {
    return UINT32_C(1) << 1;
  }
  const zs407_db32_t samples[] = {-100, -20, -80, -60};
  zs407_db32_t minimum[2];
  zs407_db32_t maximum[2];
  if (zs407_trace_envelope(samples, 4U, 2U, minimum, maximum) !=
          ZS407_CORE_OK ||
      minimum[0] != -100 || maximum[0] != -20 ||
      minimum[1] != -80 || maximum[1] != -60) {
    return UINT32_C(1) << 2;
  }
  return 0U;
}
