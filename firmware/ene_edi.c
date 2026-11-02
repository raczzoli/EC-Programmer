/* SPDX-FileCopyrightText: 2026 R89 Repairs and contributors
 * SPDX-License-Identifier: GPL-2.0-or-later
 */
/* ENE EDI register protocol and flash commands adapted from flashrom edi.c,
 * Copyright 2015 Paul Kocialkowski, GPL-2.0-or-later.
 */
#include "ene_edi.h"
#include <stddef.h>
#include "pico/stdlib.h"
#include "hardware/spi.h"

#define EDI_CS 5u
#define EDI_CLK 6u
#define EDI_MOSI 7u
#define EDI_MISO 4u
#define EDI_HWVERSION 0xff00u
#define EDI_EDIID 0xff24u
#define EDI_PXCFG 0xff14u
#define EDI_EFA0 0xfea8u
#define EDI_EFA1 0xfea9u
#define EDI_EFA2 0xfeaau
#define EDI_EFDAT 0xfeabu
#define EDI_EFCMD 0xfeacu
#define EDI_EFCFG 0xfeadu
#define EDI_PAGE 128u
#define EDI_SIZE (128u * 1024u)

static bool active;
static const char *error_text = "EDI_ERROR";
static uint8_t last_rx[36];

const char *ene_error(void) { return error_text; }
const uint8_t *ene_last_rx(void) { return last_rx; }
bool ene_is_open(void) { return active; }

static void cs_select(void) { gpio_put(EDI_CS, 0); }
static void cs_deselect(void) { gpio_put(EDI_CS, 1); }

static bool edi_write(uint16_t address, uint8_t value) {
    uint8_t cmd[5] = {0x40, 0, (uint8_t)(address >> 8), (uint8_t)address, value};
    cs_select();
    int result = spi_write_blocking(spi0, cmd, sizeof cmd);
    cs_deselect();
    if (result != sizeof cmd) { error_text = "EDI_WRITE_IO"; return false; }
    return true;
}

static bool edi_read(uint16_t address, uint8_t *value) {
    uint8_t tx[36] = {0x30, 0, (uint8_t)(address >> 8), (uint8_t)address};
    uint8_t rx[36];
    for (unsigned i = 4; i < sizeof tx; ++i) tx[i] = 0xff;
    /* ENE may return 0x5f until the value is ready, then 0x50 + value. */
    for (unsigned attempt = 0; attempt < 3; ++attempt) {
        cs_select();
        int result = spi_write_read_blocking(spi0, tx, rx, sizeof tx);
        cs_deselect();
        if (result != sizeof tx) { error_text = "EDI_READ_IO"; return false; }
        for (unsigned i = 0; i < sizeof rx; ++i) last_rx[i] = rx[i];
        for (unsigned i = 4; i + 1 < sizeof rx; ++i) {
            if (rx[i] == 0x50) { *value = rx[i + 1]; return true; }
        }
    }
    error_text = "EDI_NOT_READY";
    return false;
}

static bool config_bit(uint16_t address, uint8_t bit, bool set) {
    uint8_t value;
    if (!edi_read(address, &value)) return false;
    value = set ? (uint8_t)(value | bit) : (uint8_t)(value & ~bit);
    return edi_write(address, value);
}

static bool flash_address(uint32_t address) {
    return edi_write(EDI_EFA0, (uint8_t)address) &&
           edi_write(EDI_EFA1, (uint8_t)(address >> 8)) &&
           edi_write(EDI_EFA2, (uint8_t)(address >> 16));
}

static bool wait_ready(void) {
    absolute_time_t deadline = make_timeout_time_ms(1000);
    uint8_t cfg;
    do {
        if (!edi_read(EDI_EFCFG, &cfg)) return false;
        if (!(cfg & 0x02)) return true;
        sleep_us(10);
    } while (!time_reached(deadline));
    error_text = "EDI_FLASH_BUSY_TIMEOUT";
    return false;
}

static bool page_address(uint32_t address) {
    if (!active || (address & (EDI_PAGE - 1)) || address >= EDI_SIZE) {
        error_text = "EDI_ADDRESS";
        return false;
    }
    return true;
}

bool ene_open(uint8_t *hwversion, uint8_t *ediid) {
    if (active) {
        return edi_read(EDI_HWVERSION, hwversion) && edi_read(EDI_EDIID, ediid);
    }
    spi_init(spi0, 2000000);
    spi_set_format(spi0, 8, SPI_CPOL_0, SPI_CPHA_0, SPI_MSB_FIRST);
    gpio_set_function(EDI_CLK, GPIO_FUNC_SPI);
    gpio_set_function(EDI_MOSI, GPIO_FUNC_SPI);
    gpio_set_function(EDI_MISO, GPIO_FUNC_SPI);
    gpio_init(EDI_CS);
    gpio_put(EDI_CS, 1);
    gpio_set_dir(EDI_CS, GPIO_OUT);

    uint8_t ignored;
    (void)edi_read(EDI_HWVERSION, &ignored); /* First clock enables EDI. */
    if (!edi_read(EDI_HWVERSION, hwversion) || !edi_read(EDI_EDIID, ediid)) goto fail;
    if (!((*hwversion == 0xb0 || *hwversion == 0xd0) && *ediid == 0x0b)) {
        error_text = "EDI_UNSUPPORTED_ID";
        goto fail;
    }
    if (!config_bit(EDI_PXCFG, 0x01, true)) goto fail;
    active = true;
    return true;
fail:
    spi_deinit(spi0);
    gpio_set_function(EDI_CLK, GPIO_FUNC_SIO);
    gpio_set_function(EDI_MOSI, GPIO_FUNC_SIO);
    gpio_set_function(EDI_MISO, GPIO_FUNC_SIO);
    gpio_set_dir(EDI_CLK, GPIO_IN);
    gpio_set_dir(EDI_MOSI, GPIO_IN);
    gpio_set_dir(EDI_MISO, GPIO_IN);
    gpio_set_dir(EDI_CS, GPIO_IN);
    return false;
}

bool ene_close(void) {
    if (!active) return true;
    bool flash_disabled = config_bit(EDI_EFCFG, 0x08, false);
    bool cpu_released = config_bit(EDI_PXCFG, 0x01, false);
    uint8_t cmd = 0xf3;
    cs_select();
    spi_write_blocking(spi0, &cmd, 1);
    cs_deselect();
    spi_deinit(spi0);
    gpio_set_function(EDI_CLK, GPIO_FUNC_SIO);
    gpio_set_function(EDI_MOSI, GPIO_FUNC_SIO);
    gpio_set_function(EDI_MISO, GPIO_FUNC_SIO);
    gpio_set_dir(EDI_CLK, GPIO_IN);
    gpio_set_dir(EDI_MOSI, GPIO_IN);
    gpio_set_dir(EDI_MISO, GPIO_IN);
    gpio_set_dir(EDI_CS, GPIO_IN);
    active = false;
    return flash_disabled && cpu_released;
}

bool ene_read_page(uint32_t address, uint8_t data[EDI_PAGE]) {
    if (!page_address(address)) return false;
    if (!config_bit(EDI_EFCFG, 0x08, true)) return false;
    bool okay = true;
    for (unsigned i = 0; i < EDI_PAGE && okay; ++i) {
        /* Re-address each byte; this matches flashrom's EDI reader. */
        okay = flash_address(address + i) && edi_write(EDI_EFCMD, 0x03) &&
               edi_read(EDI_EFDAT, &data[i]);
    }
    if (!config_bit(EDI_EFCFG, 0x08, false)) okay = false;
    return okay;
}

bool ene_erase_page(uint32_t address) {
    if (!page_address(address)) return false;
    if (!config_bit(EDI_EFCFG, 0x08, true)) return false;
    bool okay = flash_address(address) && edi_write(EDI_EFCMD, 0x20) &&
                wait_ready();
    if (!config_bit(EDI_EFCFG, 0x08, false)) okay = false;
    return okay;
}

bool ene_write_page(uint32_t address, const uint8_t data[EDI_PAGE]) {
    if (!page_address(address)) return false;
    if (!config_bit(EDI_EFCFG, 0x08, true)) return false;
    bool okay = edi_write(EDI_EFCMD, 0x80);
    for (unsigned i = 0; i < EDI_PAGE && okay; ++i) {
        okay = flash_address(address + i) &&
               edi_write(EDI_EFDAT, data[i]) &&
               edi_write(EDI_EFCMD, 0x02);
    }
    if (okay) okay = edi_write(EDI_EFCMD, 0x70) && wait_ready();
    if (!config_bit(EDI_EFCFG, 0x08, false)) okay = false;
    return okay;
}
