/* SPDX-FileCopyrightText: 2026 R89 Repairs and contributors
 * SPDX-License-Identifier: GPL-2.0-or-later
 */
#include "ite_bus.h"
#include "ite_dbgr.h"
uint64_t dbgr_hold_until_us, dbgr_next_feed_us;
/* Some targets keep the watchdog running after the disable sequence.
 * Feed only after a successful DBGR entry; expire the hold automatically
 * after 30 seconds without an operation.
 */
void dbgr_end_session(void) {
    dbgr_hold_until_us = 0;
    wave_entry_rate = 0;
    release_bus();
}
void dbgr_hold_refresh(void) {
    dbgr_hold_until_us = time_us_64() + 30000000u;
    dbgr_next_feed_us = time_us_64() + 10000u;
}

void dbgr_hold_tick(void) {
    if (!dbgr_hold_until_us) return;
    uint64_t now = time_us_64();
    if (now >= dbgr_hold_until_us) {
        dbgr_hold_until_us = 0;
        return;
    }
    if (now < dbgr_next_feed_us) return;
    uint8_t saved_register;
    bool restore = bus_selected_register(&saved_register);
    if (!dbgr_reg_write(0x2f, 0x1f) ||
        !dbgr_reg_write(0x2e, 0x07) ||
        !dbgr_reg_write(0x30, 0x5c)) {
        dbgr_hold_until_us = 0;
        return;
    }
    /* Legacy hosts split register selection and data across USB requests.
     * Keep their cursor intact when feeding between those requests. */
    if (restore && !write_i2c(0x5a, &saved_register, 1)) {
        dbgr_hold_until_us = 0;
        return;
    }
    dbgr_next_feed_us = time_us_64() + 10000u;
}

