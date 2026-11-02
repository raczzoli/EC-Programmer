/* SPDX-FileCopyrightText: 2026 R89 Repairs and contributors
 * SPDX-License-Identifier: GPL-2.0-or-later
 */
#pragma once
#include <stdbool.h>
#include <stdint.h>
extern uint64_t dbgr_hold_until_us, dbgr_next_feed_us;
extern unsigned wave_entry_rate;
void waveform(bool settle, unsigned frequency);
void wave_at_power_on(void);
bool dbgr_reg_write(uint8_t reg, uint8_t value);
bool dbgr_reg_read(uint8_t reg, uint8_t *value);
void dbgr_hold_refresh(void);
void dbgr_hold_tick(void);
void enter_dbgr_fast(void);
void dbgr_end_session(void);
