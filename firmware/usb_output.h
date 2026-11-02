/* SPDX-FileCopyrightText: 2026 R89 Repairs and contributors
 * SPDX-License-Identifier: GPL-2.0-or-later
 */
#pragma once
#include <stdbool.h>
#include <stdint.h>
void usb_reply_begin(bool tagged, uint32_t tag);
void usb_printf(const char *format, ...) __attribute__((format(printf, 1, 2)));
void usb_puts(const char *text);
