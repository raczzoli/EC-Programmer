/* SPDX-FileCopyrightText: 2026 R89 Repairs and contributors
 * SPDX-License-Identifier: GPL-2.0-or-later
 */
#include "ite_bus.h"
#include "hardware/gpio.h"
#define CLOCK_TIMEOUT_US 25000
uint sda_pin = 7, scl_pin = 6;
const char *i2c_error;
static uint8_t selected_register;
static bool selected_register_valid;
static uint64_t command_deadline;
static unsigned bit_delay_us = 5;

void bus_set_deadline(unsigned milliseconds) {
    command_deadline = milliseconds ? time_us_64() + milliseconds * 1000ull : 0;
}
bool bus_set_timing(unsigned delay_us) {
    if (delay_us != 5 && delay_us != 3 && delay_us != 2) return false;
    bit_delay_us = delay_us;
    return true;
}
unsigned bus_timing(void) { return bit_delay_us; }
bool bus_selected_register(uint8_t *reg) {
    *reg = selected_register;
    return selected_register_valid;
}
static bool within_deadline(void) {
    if (command_deadline && time_us_64() >= command_deadline) {
        i2c_error = "COMMAND_TIMEOUT";
        return false;
    }
    return true;
}
void release_pin(uint pin) { gpio_set_dir(pin, GPIO_IN); }
void low_pin(uint pin) { gpio_put(pin, 0); gpio_set_dir(pin, GPIO_OUT); }
void release_bus(void) { release_pin(sda_pin); release_pin(scl_pin); }
static bool clock_high(void) {
    release_pin(scl_pin);
    if (!within_deadline()) return false;
    absolute_time_t end = make_timeout_time_us(CLOCK_TIMEOUT_US);
    while (!gpio_get(scl_pin)) {
        if (!within_deadline()) return false;
        if (time_reached(end)) {
            i2c_error = "SCL_LOW_TIMEOUT";
            return false;
        }
    }
    sleep_us(bit_delay_us);
    return true;
}
static bool start(void) {
    release_bus(); sleep_us(5);
    if (!gpio_get(sda_pin)) {
        i2c_error = "SDA_LOW_BEFORE_START";
        return false;
    }
    if (!clock_high()) return false;
    low_pin(sda_pin); sleep_us(5); low_pin(scl_pin); return true;
}
static void stop(void) {
    low_pin(sda_pin); sleep_us(5);
    if (clock_high()) { release_pin(sda_pin); sleep_us(5); }
    release_bus();
}
static bool bit_out(bool value) {
    if (!within_deadline()) return false;
    if (value) release_pin(sda_pin); else low_pin(sda_pin);
    sleep_us(bit_delay_us);
    if (!clock_high()) return false;
    low_pin(scl_pin); sleep_us(bit_delay_us); return true;
}
static bool bit_in(bool *value) {
    release_pin(sda_pin); sleep_us(bit_delay_us);
    if (!clock_high()) return false;
    *value = gpio_get(sda_pin);
    low_pin(scl_pin); sleep_us(bit_delay_us); return true;
}
static bool byte_out(uint8_t value) {
    for (int i = 7; i >= 0; --i) if (!bit_out((value >> i) & 1)) return false;
    bool nack = true;
    return bit_in(&nack) && !nack;
}
static bool byte_in(uint8_t *value, bool ack) {
    *value = 0;
    for (int i = 0; i < 8; ++i) {
        bool bit;
        if (!bit_in(&bit)) return false;
        *value = (uint8_t)((*value << 1) | bit);
    }
    return bit_out(!ack);
}
bool write_i2c(uint8_t addr, const uint8_t *buf, size_t len) {
    i2c_error = NULL;
    bool ok = start();
    if (ok && !byte_out(addr << 1)) {
        if (!i2c_error) i2c_error = "ADDRESS_NACK";
        ok = false;
    }
    for (size_t i = 0; ok && i < len; ++i) {
        if (!byte_out(buf[i])) {
            if (!i2c_error) i2c_error = "DATA_NACK";
            ok = false;
        }
    }
    stop();
    if (ok && addr == 0x5a && len == 1) {
        selected_register = buf[0];
        selected_register_valid = true;
    }
    return ok;
}
bool probe_write_address(uint8_t addr) {
    i2c_error = NULL;
    bool ok = start();
    if (ok && !byte_out(addr << 1)) {
        if (!i2c_error) i2c_error = "ADDRESS_NACK";
        ok = false;
    }
    stop();
    return ok;
}
bool read_i2c(uint8_t addr, uint8_t *buf, size_t len) {
    i2c_error = NULL;
    bool ok = start();
    if (ok && !byte_out((addr << 1) | 1)) {
        if (!i2c_error) i2c_error = "ADDRESS_NACK";
        ok = false;
    }
    for (size_t i = 0; ok && i < len; ++i) ok = byte_in(&buf[i], i + 1 < len);
    stop(); return ok;
}
void set_pins(uint sda, uint scl) {
    if (sda != sda_pin || scl != scl_pin) selected_register_valid = false;
    release_bus(); sda_pin = sda; scl_pin = scl;
    gpio_init(sda_pin); gpio_init(scl_pin);
    gpio_disable_pulls(sda_pin); gpio_disable_pulls(scl_pin);
    gpio_put(sda_pin, 0); gpio_put(scl_pin, 0); release_bus();
}
bool valid_pin(uint p) { return p <= 22 || (p >= 26 && p <= 28); }
bool adjacent_bus_pins(void) {
    return scl_pin == sda_pin + 1 || sda_pin == scl_pin + 1;
}
