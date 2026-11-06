/* SPDX-FileCopyrightText: 2026 R89 Repairs and contributors
 * SPDX-License-Identifier: GPL-2.0-or-later
 */
/* EDI register/flash sequence adapted from flashrom edi.c,
 * Copyright 2015 Paul Kocialkowski, GPL-2.0-or-later. See docs/ENE.md.
 */
#include "ene_edi.h"
#include <stddef.h>
#include <string.h>
#include "pico/stdlib.h"
#include "hardware/spi.h"
#define EDI_CS 5u
#define EDI_CLK 6u
#define EDI_MOSI 7u
#define EDI_MISO 4u
#define EDI_HWVERSION 0xff00u
#define EDI_EDIID 0xff24u
#define EDI_PXCFG 0xff14u
#define EDI_WDTCFG 0xfe80u
#define EDI_EFA0 0xfea8u
#define EDI_EFA1 0xfea9u
#define EDI_EFA2 0xfeaau
#define EDI_EFDAT 0xfeabu
#define EDI_EFCMD 0xfeacu
#define EDI_EFCFG 0xfeadu
#define EDI_PAGE 128u
#define EDI_ENTRY_TRIES 50u

typedef struct {
    const char *family;
    uint8_t hw, id;
    uint32_t size;
    bool disable_watchdog;
} edi_variant;
/* Match both bytes: EDIID 07 alone does not identify the entry variant.
 * Only F0/07 has evidence for watchdog-disable value 0x48.
 */
static const edi_variant variants[] = {
    {"KB901X",   0xc3, 0x04, 128u * 1024u, false},
    {"KB902X",   0xb1, 0x07, 128u * 1024u, false},
    {"KB902X",   0xc0, 0x07, 128u * 1024u, false},
    {"KB9052",   0xb0, 0x0b, 128u * 1024u, false},
    {"KB9052",   0xd0, 0x0b, 128u * 1024u, false},
    {"KB9542GF", 0xa0, 0x07, 160u * 1024u, false},
    {"KB9542GF", 0xf0, 0x07, 160u * 1024u, true},
};
static const edi_variant *selected;
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
    if (result != (int)sizeof cmd) { error_text = "EDI_WRITE_IO"; return false; }
    return true;
}
static bool edi_read(uint16_t address, uint8_t *value) {
    uint8_t tx[36] = {0x30, 0, (uint8_t)(address >> 8), (uint8_t)address};
    uint8_t rx[36];
    memset(tx + 4, 0xff, sizeof tx - 4);
    /* Busy bytes precede READY + data. Never accept a stray READY in noise.
     * READY without a following byte requires another complete transaction.
     */
    for (unsigned attempt = 0; attempt < 3; ++attempt) {
        cs_select();
        int result = spi_write_read_blocking(spi0, tx, rx, sizeof tx);
        cs_deselect();
        if (result != (int)sizeof tx) { error_text = "EDI_READ_IO"; return false; }
        memcpy(last_rx, rx, sizeof last_rx);
        for (unsigned i = 4; i + 1 < sizeof rx; ++i) {
            if (rx[i] == 0x50) { *value = rx[i + 1]; return true; }
            if (rx[i] != 0x5f) break;
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
static bool session_state(bool flash_enabled) {
    uint8_t cfg, cpu;
    if (!edi_read(EDI_PXCFG, &cpu)) return false;
    if (!(cpu & 0x01)) { error_text = "EDI_SESSION_LOST"; return false; }
    if (flash_enabled) {
        if (!edi_read(EDI_EFCFG, &cfg)) return false;
        if (!(cfg & 0x08)) { error_text = "EDI_SESSION_LOST"; return false; }
    }
    return true;
}
static bool page_address(uint32_t address) {
    if (!active || !selected) { error_text = "EDI_NOT_OPEN"; return false; }
    if ((address & (EDI_PAGE - 1)) || address > selected->size - EDI_PAGE) {
        error_text = "EDI_ADDRESS";
        return false;
    }
    return true;
}
static void release_pins(void) {
    spi_deinit(spi0);
    const unsigned pins[] = {EDI_CLK, EDI_MOSI, EDI_MISO, EDI_CS};
    for (unsigned i = 0; i < sizeof pins / sizeof pins[0]; ++i) {
        gpio_set_function(pins[i], GPIO_FUNC_SIO);
        gpio_set_dir(pins[i], GPIO_IN);
    }
    active = false;
    selected = NULL;
}
static bool disable_edi(void) {
    const uint8_t cmd = 0xf3;
    cs_select();
    int result = spi_write_blocking(spi0, &cmd, 1);
    cs_deselect();
    if (result != 1) { error_text = "EDI_DISABLE_IO"; return false; }
    return true;
}
static bool release_cpu(void) {
    for (unsigned i = 0; i < 10; ++i) {
        uint8_t cfg;
        if (config_bit(EDI_PXCFG, 0x01, false) && edi_read(EDI_PXCFG, &cfg) && !(cfg & 1))
            return true;
        sleep_us(50000);
    }
    error_text = "EDI_CPU_RELEASE";
    return false;
}
bool ene_open(uint8_t *hwversion, uint8_t *ediid) {
    return ene_open_family("KB9052", hwversion, ediid);
}
bool ene_open_family(const char *family, uint8_t *hwversion, uint8_t *ediid) {
    bool known_family = false, reset_attempted = false;
    for (unsigned i = 0; i < sizeof variants / sizeof variants[0]; ++i)
        if (!strcmp(family, variants[i].family)) known_family = true;
    if (!known_family) { error_text = "EDI_FAMILY"; return false; }
    if (active) {
        if (strcmp(family, selected->family)) { error_text = "EDI_FAMILY_MISMATCH"; return false; }
        if (!edi_read(EDI_HWVERSION, hwversion) || !edi_read(EDI_EDIID, ediid)) return false;
        if (*hwversion != selected->hw || *ediid != selected->id) {
            error_text = "EDI_ID_CHANGED"; return false;
        }
        return session_state(false);
    }
    selected = NULL;
    *hwversion = *ediid = 0;
    spi_init(spi0, 2000000);
    spi_set_format(spi0, 8, SPI_CPOL_0, SPI_CPHA_0, SPI_MSB_FIRST);
    gpio_init(EDI_CS);
    gpio_put(EDI_CS, 1);
    gpio_set_dir(EDI_CS, GPIO_OUT);
    gpio_set_function(EDI_CLK, GPIO_FUNC_SPI);
    gpio_set_function(EDI_MOSI, GPIO_FUNC_SPI);
    gpio_set_function(EDI_MISO, GPIO_FUNC_SPI);
    for (unsigned attempt = 0; attempt < EDI_ENTRY_TRIES; ++attempt) {
        uint8_t ignored;
        (void)edi_read(EDI_HWVERSION, &ignored); /* First clock enables EDI. */
        if (edi_read(EDI_HWVERSION, hwversion) && edi_read(EDI_EDIID, ediid) &&
            *hwversion != 0 && *hwversion != 0xff && *ediid != 0 && *ediid != 0xff) {
            for (unsigned i = 0; i < sizeof variants / sizeof variants[0]; ++i) {
                if (*hwversion == variants[i].hw && *ediid == variants[i].id) {
                    if (strcmp(family, variants[i].family)) {
                        error_text = "EDI_FAMILY_MISMATCH"; goto fail;
                    }
                    selected = &variants[i];
                    break;
                }
            }
            if (!selected) { error_text = "EDI_UNSUPPORTED_ID"; goto fail; }
            break;
        }
        sleep_us(100000);
    }
    if (!selected) { error_text = "EDI_NO_DEVICE"; goto fail; }
    for (unsigned attempt = 0; attempt < EDI_ENTRY_TRIES; ++attempt) {
        reset_attempted = true;
        if (config_bit(EDI_PXCFG, 0x01, true) && session_state(false)) {
            if (selected->disable_watchdog && !edi_write(EDI_WDTCFG, 0x48)) goto fail;
            active = true;
            return true;
        }
        sleep_us(100000);
    }
    error_text = "EDI_CPU_RESET";
fail:;
    const char *cause = error_text;
    if (reset_attempted) (void)release_cpu();
    (void)disable_edi();
    release_pins();
    error_text = cause;
    return false;
}
bool ene_close(void) {
    if (!active) return true;
    bool flash_disabled = config_bit(EDI_EFCFG, 0x08, false);
    bool cpu_released = release_cpu();
    bool disabled = disable_edi();
    release_pins();
    return flash_disabled && cpu_released && disabled;
}
static bool finish_page(bool okay) {
    if (okay) okay = session_state(true);
    const char *cause = error_text;
    bool disabled = config_bit(EDI_EFCFG, 0x08, false);
    if (!okay) error_text = cause; /* Preserve the first failure over cleanup. */
    return okay && disabled;
}
static bool begin_page(uint32_t address) {
    if (!page_address(address) || !session_state(false)) return false;
    if (!config_bit(EDI_EFCFG, 0x08, true)) return finish_page(false);
    if (!session_state(true)) return finish_page(false);
    return true;
}
bool ene_read_page(uint32_t address, uint8_t data[EDI_PAGE]) {
    if (!begin_page(address)) return false;
    bool okay = true;
    for (unsigned i = 0; i < EDI_PAGE && okay; ++i) {
        okay = flash_address(address + i) && edi_write(EDI_EFCMD, 0x03) &&
               edi_read(EDI_EFDAT, &data[i]);
    }
    return finish_page(okay);
}
bool ene_erase_page(uint32_t address) {
    if (!begin_page(address)) return false;
    bool okay = flash_address(address) && edi_write(EDI_EFCMD, 0x20) && wait_ready();
    return finish_page(okay);
}
bool ene_write_page(uint32_t address, const uint8_t data[EDI_PAGE]) {
    if (!begin_page(address)) return false;
    bool okay = edi_write(EDI_EFCMD, 0x80);
    for (unsigned i = 0; i < EDI_PAGE && okay; ++i) {
        okay = flash_address(address + i) && edi_write(EDI_EFDAT, data[i]) &&
               edi_write(EDI_EFCMD, 0x02);
    }
    if (okay) okay = edi_write(EDI_EFCMD, 0x70) && wait_ready();
    return finish_page(okay);
}
