/* SPDX-FileCopyrightText: 2026 R89 Repairs and contributors
 * SPDX-License-Identifier: GPL-2.0-or-later
 */
#pragma once
#include <stdbool.h>
#include <stddef.h>
#include "usb_commands.h"
typedef struct {
    char text[MAX_LINE];
    size_t length;
    bool discard;
} command_buffer;
/* 1 = complete line, -1 = overflow, 0 = waiting/discarding. */
static inline int command_feed(command_buffer *buffer, int c) {
    if (c == '\n' || c == '\r') {
        if (buffer->discard) { buffer->discard=false; buffer->length=0; return 0; }
        if (!buffer->length) return 0;
        buffer->text[buffer->length]=0;
        buffer->length=0;
        return 1;
    }
    if (buffer->discard || c < 32 || c >= 127) return 0;
    if (buffer->length+1 < sizeof buffer->text) {
        buffer->text[buffer->length++]=(char)c;
        return 0;
    }
    buffer->length=0;
    buffer->discard=true;
    return -1;
}
