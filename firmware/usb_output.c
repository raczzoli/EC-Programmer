/* SPDX-FileCopyrightText: 2026 R89 Repairs and contributors
 * SPDX-License-Identifier: GPL-2.0-or-later
 */
#include "usb_output.h"
#include <stdarg.h>
#include <stdio.h>
#include <string.h>

static bool use_tag, line_start = true;
static uint32_t request_tag;
void usb_reply_begin(bool tagged, uint32_t tag) {
    use_tag = tagged;
    request_tag = tag;
    line_start = true;
}
void usb_printf(const char *format, ...) {
    /* Commands execute serially on core 0. Keep formatting off the small
     * MCU stack and emit chunks, not one USB stdio call per character. */
    static char text[640];
    va_list args;
    va_start(args, format);
    vsnprintf(text, sizeof text, format, args);
    va_end(args);
    for (const char *p = text; *p; ) {
        if (line_start && use_tag) printf("@%08lX ", (unsigned long)request_tag);
        const char *newline = strchr(p, '\n');
        size_t count = newline ? (size_t)(newline-p)+1 : strlen(p);
        printf("%.*s", (int)count, p);
        line_start = newline != NULL;
        p += count;
    }
}
void usb_puts(const char *text) { usb_printf("%s\n", text); }
