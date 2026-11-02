/* SPDX-FileCopyrightText: 2026 R89 Repairs and contributors
 * SPDX-License-Identifier: GPL-2.0-or-later
 */
#pragma once
#include <stdint.h>
#include <stdbool.h>
typedef unsigned uint;
uint64_t time_us_64(void);
void sleep_us(uint64_t us);
