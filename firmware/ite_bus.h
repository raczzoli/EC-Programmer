/* SPDX-FileCopyrightText: 2026 R89 Repairs and contributors
 * SPDX-License-Identifier: GPL-2.0-or-later
 */
#pragma once
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include "pico/stdlib.h"
extern uint sda_pin, scl_pin;
extern const char *i2c_error;
void release_pin(uint pin);
void low_pin(uint pin);
void release_bus(void);
bool write_i2c(uint8_t addr, const uint8_t *buf, size_t len);
bool probe_write_address(uint8_t addr);
bool read_i2c(uint8_t addr, uint8_t *buf, size_t len);
void set_pins(uint sda, uint scl);
bool valid_pin(uint pin);
bool adjacent_bus_pins(void);
bool bus_selected_register(uint8_t *reg);
void bus_set_deadline(unsigned milliseconds);
bool bus_set_timing(unsigned delay_us);
unsigned bus_timing(void);
