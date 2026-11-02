/* SPDX-FileCopyrightText: 2026 R89 Repairs and contributors
 * SPDX-License-Identifier: GPL-2.0-or-later
 */
#include "pico/stdlib.h"
#include "ite_bus.h"
#include "ite_dbgr.h"
#include "usb_commands.h"
#include "line_reader.h"
#include <stdio.h>
static command_buffer input;
int main(void) {
    stdio_init_all(); set_pins(7,6);
    while (true) {
        int c=getchar_timeout_us(5000);
        if (c==PICO_ERROR_TIMEOUT) { dbgr_hold_tick(); continue; }
        int ready = command_feed(&input,c);
        if (ready > 0) usb_command(input.text);
        else if (ready < 0) { release_bus(); puts("ERR LINE_TOO_LONG"); }
    }
}
