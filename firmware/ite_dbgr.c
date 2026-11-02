/* SPDX-FileCopyrightText: 2026 R89 Repairs and contributors
 * SPDX-License-Identifier: GPL-2.0-or-later
 */
#include <string.h>
#include "ite_bus.h"
#include "ite_dbgr.h"
#include "usb_output.h"
#include "hardware/pio.h"
#include "hardware/dma.h"
#include "hardware/clocks.h"
#include "hardware/gpio.h"
#include "dbgr_open_drain.pio.h"
unsigned wave_entry_rate;
static uint8_t pio_bus_bits(uint8_t state) {
    /* state bit0=SCL, bit1=SDA; OUT PINDIRS bit0 is the lower GPIO. */
    return scl_pin < sda_pin ? state :
           (uint8_t)(((state & 1u) << 1) | ((state & 2u) >> 1));
}
/* Chromium OS iteflash FTDI waveform: bit0=SCL, bit1=SDA.
 * HIGH is Hi-Z; the target board supplies the pull-ups.
 */
static void wave_step(uint8_t state, uint64_t *deadline, unsigned step) {
    if (state & 1) release_pin(scl_pin); else low_pin(scl_pin);
    if (state & 2) release_pin(sda_pin); else low_pin(sda_pin);
    *deadline += (step & 1) ? 3 : 2; /* nominal 2.5 us per state */
    busy_wait_until(from_us_since_boot(*deadline));
}
static void waveform_soft(bool settle) {
    static const uint8_t pattern[8] = {2,3,1,1,3,2,0,0};
    low_pin(scl_pin); low_pin(sda_pin); sleep_ms(5);
    uint64_t deadline = time_us_64();
    unsigned step = 0;
    for (int word = 0; word < 24; ++word) {
        uint8_t state = (word == 19) ? 3 : (word % 3 == 1 ? 2 : 0);
        for (int i = 0; i < 8; ++i) wave_step(state, &deadline, step++);
    }
    for (int i = 0; i < 40000 - 24 * 8; ++i)
        wave_step(pattern[i & 7], &deadline, step++);
    release_bus();
    if (settle) sleep_ms(10);
}

/* PIO emits the Chromium 24-word preamble and 40000 states at 400k states/s.
 * Its FTDI setup specifies 2.5 us per state; this takes about 100 ms.
 * OUT PINDIRS, not OUT PINS, makes a HIGH state an input/Hi-Z.
 * PIO uses consecutive GPIOs; pio_bus_bits maps each signal to its GPIO.
 */
#define WAVE_STATES 40000
#define WAVE_WORDS (WAVE_STATES / 16)
static uint32_t wave_words[WAVE_WORDS];
static void waveform_pio(bool settle, unsigned frequency) {
    static const uint8_t pattern[8] = {2,3,1,1,3,2,0,0};
    memset(wave_words, 0, sizeof wave_words);
    for (unsigned n = 0; n < WAVE_STATES; ++n) {
        uint8_t state;
        if (n < 24 * 8) {
            unsigned word = n / 8;
            state = (word == 19) ? 3 : (word % 3 == 1 ? 2 : 0);
        } else {
            state = pattern[(n - 24 * 8) & 7];
        }
        uint8_t high = pio_bus_bits(state);
        uint8_t dirs = (~high) & 3;
        wave_words[n / 16] |= (uint32_t)dirs << (2 * (n & 15));
    }

    PIO pio = pio1;
    uint sm = pio_claim_unused_sm(pio, true);
    uint offset = pio_add_program(pio, &dbgr_open_drain_program);
    pio_sm_config cfg = dbgr_open_drain_program_get_default_config(offset);
    sm_config_set_out_pins(&cfg, sda_pin < scl_pin ? sda_pin : scl_pin, 2);
    sm_config_set_out_shift(&cfg, true, true, 32);
    sm_config_set_clkdiv(&cfg, (float)clock_get_hz(clk_sys) / (float)frequency);

    low_pin(sda_pin); low_pin(scl_pin);
    pio_gpio_init(pio, sda_pin); pio_gpio_init(pio, scl_pin);
    pio_sm_init(pio, sm, offset, &cfg);
    uint32_t mask = (1u << sda_pin) | (1u << scl_pin);
    pio_sm_set_pins_with_mask(pio, sm, 0, mask);
    pio_sm_set_pindirs_with_mask(pio, sm, mask, mask);

    int dma = dma_claim_unused_channel(true);
    dma_channel_config dma_cfg = dma_channel_get_default_config(dma);
    channel_config_set_transfer_data_size(&dma_cfg, DMA_SIZE_32);
    channel_config_set_read_increment(&dma_cfg, true);
    channel_config_set_write_increment(&dma_cfg, false);
    channel_config_set_dreq(&dma_cfg, pio_get_dreq(pio, sm, true));
    dma_channel_configure(dma, &dma_cfg, &pio->txf[sm], wave_words,
                          WAVE_WORDS, true); /* prefill FIFO, then wait for PIO */
    sleep_ms(5);

    pio_sm_set_enabled(pio, sm, true);
    dma_channel_wait_for_finish_blocking(dma);
    while (!pio_sm_is_tx_fifo_empty(pio, sm)) tight_loop_contents();
    /* FIFO empty can leave 16 states in OSR. Include a full last word at
     * the selected rate (80 us at 200k, 40 us at 400k), plus rounding margin. */
    sleep_us((16000000u + frequency - 1u) / frequency + 1u);
    pio_sm_set_enabled(pio, sm, false);
    release_bus(); /* preset SIO directions before changing GPIO function */
    gpio_set_function(sda_pin, GPIO_FUNC_SIO);
    gpio_set_function(scl_pin, GPIO_FUNC_SIO);
    dma_channel_unclaim(dma);
    pio_sm_unclaim(pio, sm);
    pio_remove_program(pio, &dbgr_open_drain_program, offset);
    if (settle) sleep_ms(10);
}

void waveform(bool settle, unsigned frequency) {
    if (adjacent_bus_pins()) waveform_pio(settle, frequency);
    else waveform_soft(settle);
}

void wave_at_power_on(void) {
    release_bus();
    usb_puts("READY WAVEPOWER WAIT_POWER_OFF");
    absolute_time_t timeout = make_timeout_time_ms(40000);
    uint64_t low_since = 0;
    while (!time_reached(timeout)) {
        if (!gpio_get(scl_pin)) {
            if (!low_since) low_since = time_us_64();
            if (time_us_64() - low_since >= 100000u) break;
        } else low_since = 0;
        sleep_ms(1);
    }
    if (time_reached(timeout)) { usb_puts("ERR WAVEPOWER_NO_POWER_OFF"); return; }
    usb_puts("POWER_OFF_DETECTED WAIT_POWER_ON");
    while (!gpio_get(scl_pin) && !time_reached(timeout)) tight_loop_contents();
    if (time_reached(timeout)) { usb_puts("ERR WAVEPOWER_NO_POWER_ON"); return; }
    static const unsigned rates[] = {800000, 600000, 400000, 300000};
    wave_entry_rate = 0;
    for (unsigned i = 0; i < sizeof rates / sizeof rates[0]; ++i) {
        waveform(false, rates[i]);
        /* Select DBGR immediately while the entry window is open. */
        uint8_t reg = 0x07, value = 0x7f;
        if (write_i2c(0x5a, &reg, 1) && write_i2c(0x35, &value, 1)) {
            wave_entry_rate = rates[i];
            usb_printf("WAVEPOWER %u ADDRESS_ACK\n", rates[i]);
            return;
        }
    }
    usb_printf("WAVEPOWER 0 %s\n", i2c_error ? i2c_error : "I2C_UNKNOWN");
}

bool dbgr_reg_write(uint8_t reg, uint8_t value) {
    return write_i2c(0x5a, &reg, 1) && write_i2c(0x35, &value, 1);
}

bool dbgr_reg_read(uint8_t reg, uint8_t *value) {
    return write_i2c(0x5a, &reg, 1) && read_i2c(0x35, value, 1);
}

void enter_dbgr_fast(void) {
    dbgr_hold_until_us = 0;
    if (!adjacent_bus_pins()) { usb_puts("ERR ENTERDBGR_PINS"); return; }
    static const unsigned rates[] = {200000, 300000, 400000,
                                     500000, 600000, 800000};
    unsigned selected_rate = 0;
    if (wave_entry_rate) {
        if (dbgr_reg_write(0x07, 0x7f)) selected_rate = wave_entry_rate;
        wave_entry_rate = 0;
    }
    for (unsigned i = 0; !selected_rate &&
                         i < sizeof rates / sizeof rates[0]; ++i) {
        waveform(false, rates[i]);
        if (dbgr_reg_write(0x07, 0x7f)) {
            selected_rate = rates[i];
            break;
        }
    }
    if (!selected_rate) {
        usb_printf("ERR ENTERDBGR_NO_ACK %s\n",
               i2c_error ? i2c_error : "I2C_UNKNOWN");
        return;
    }
    static const uint8_t stop_sequence[][2] = {
        {0x06, 0xff}, {0x05, 0xfe}, {0x04, 0}, {0x08, 0},
        {0x07, 0}, {0x06, 0}
    };
    for (unsigned i = 0; i < sizeof stop_sequence / sizeof stop_sequence[0]; ++i) {
        if (!dbgr_reg_write(stop_sequence[i][0], stop_sequence[i][1])) {
            usb_printf("ERR ENTERDBGR_STOP_%u %s\n", i,
                   i2c_error ? i2c_error : "I2C_UNKNOWN");
            return;
        }
    }
    uint8_t ver, high, low;
    if (!dbgr_reg_read(0x02, &ver) ||
        !dbgr_reg_read(0x00, &high) ||
        !dbgr_reg_read(0x01, &low)) {
        usb_printf("ERR ENTERDBGR_ID %s\n",
               i2c_error ? i2c_error : "I2C_UNKNOWN");
        return;
    }
    static const uint8_t watchdog_sequence[][2] = {
        /* Restart at F01F07, then disable via F01F05. */
        {0x2f, 0x1f}, {0x2e, 0x07}, {0x30, 0x5c},
        {0x2f, 0x1f}, {0x2e, 0x05}, {0x30, 0x10}
    };
    for (unsigned i = 0; i < sizeof watchdog_sequence / sizeof watchdog_sequence[0]; ++i) {
        if (!dbgr_reg_write(watchdog_sequence[i][0], watchdog_sequence[i][1])) {
            usb_printf("ERR ENTERDBGR_WDT_%u %s\n", i,
                   i2c_error ? i2c_error : "I2C_UNKNOWN");
            return;
        }
    }
    sleep_ms(1);
    if (!dbgr_reg_write(0x30, 0x30)) {
        usb_printf("ERR ENTERDBGR_WDT_FINAL %s\n",
               i2c_error ? i2c_error : "I2C_UNKNOWN");
        return;
    }
    sleep_ms(1);
    uint8_t watchdog;
    if (!dbgr_reg_write(0x2f, 0x1f) ||
        !dbgr_reg_write(0x2e, 0x05) ||
        !dbgr_reg_read(0x30, &watchdog)) {
        usb_printf("ERR ENTERDBGR_WDT_READ %s\n",
               i2c_error ? i2c_error : "I2C_UNKNOWN");
        return;
    }
    usb_printf("ENTERDBGR RATE=%u CHIPID=%02X%02X CHIPVER=%02X WDT=%02X\n",
           selected_rate, high, low, ver, watchdog);
    dbgr_hold_refresh();
}

