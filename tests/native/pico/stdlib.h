/* SPDX-FileCopyrightText: 2026 R89 Repairs and contributors
 * SPDX-License-Identifier: GPL-2.0-or-later
 */
#pragma once
#include <stdint.h>
#include <stdbool.h>
typedef unsigned uint;
uint64_t time_us_64(void);
void sleep_us(uint64_t us);
typedef uint64_t absolute_time_t;
absolute_time_t make_timeout_time_ms(uint32_t ms);
bool time_reached(absolute_time_t deadline);
#define GPIO_FUNC_SPI 1
#define GPIO_FUNC_SIO 5
#define GPIO_IN false
#define GPIO_OUT true
void gpio_init(unsigned pin);
void gpio_put(unsigned pin, bool value);
void gpio_set_dir(unsigned pin, bool output);
void gpio_set_function(unsigned pin, unsigned function);
