/* SPDX-FileCopyrightText: 2026 R89 Repairs and contributors
 * SPDX-License-Identifier: GPL-2.0-or-later
 */
#include "ite_flash.h"
#include "ite_bus.h"
#include "ite_dbgr.h"
#include "usb_output.h"
static uint8_t spi_last_status;
/* Legacy ITE AAI block used by CHIPVER revisions below 0x03. Keep each
 * transaction on the Pico so the host does not need ~60 USB round trips.
 * The register order follows Chromium EC util/iteflash.cc command_write_pages.
 */
static bool spi_short_command(uint8_t opcode) {
    const uint8_t sequence[][2] = {
        {0x05, 0xfe}, {0x08, 0}, {0x05, 0xfd}, {0x08, opcode}
    };
    for (unsigned i = 0; i < sizeof sequence / sizeof sequence[0]; ++i) {
        if (!dbgr_reg_write(sequence[i][0], sequence[i][1])) return false;
    }
    return true;
}

static bool spi_wait_status_for(uint8_t mask, uint8_t expected, uint64_t timeout_us) {
    if (!spi_short_command(0x05)) return false;
    uint64_t deadline = time_us_64() + timeout_us;
    do {
        uint8_t status;
        if (!read_i2c(0x35, &status, 1)) return false;
        spi_last_status = status;
        if ((status & mask) == expected) return true;
        /* Feeding WDT changes the selected DBGR register. Reissue RDSR
         * afterwards before reading 0x35 again. */
        if (time_us_64() >= dbgr_next_feed_us) {
            dbgr_hold_tick();
            if (!dbgr_hold_until_us || !spi_short_command(0x05)) return false;
        }
        sleep_us(200);
    } while (time_us_64() < deadline);
    i2c_error = "SPI_STATUS_TIMEOUT";
    return false;
}
static bool spi_wait_status(uint8_t mask, uint8_t expected) {
    return spi_wait_status_for(mask, expected, 5000000u);
}

void flash_status(void) {
    uint8_t status;
    if (!spi_short_command(0x05) || !read_i2c(0x35,&status,1)) {
        usb_printf("ERR %s\n", i2c_error ? i2c_error : "SPI_STATUS"); return;
    }
    usb_printf("STATUS %02X\n", status);
}

static bool flash_follow(void) {
    const uint8_t follow[][2] = {
        {0x07,0x7f}, {0x06,0xff}, {0x05,0xfe}, {0x04,0}, {0x08,0}
    };
    for (unsigned i=0; i<sizeof follow/sizeof follow[0]; ++i)
        if (!dbgr_reg_write(follow[i][0],follow[i][1])) return false;
    return true;
}

void flash_identify(uint8_t port) {
    uint8_t id[3];
    if (!flash_follow() || !spi_short_command(0x9f) || !read_i2c(port,id,3)) {
        usb_printf("ERR %s\n", i2c_error ? i2c_error : "FLASH_ID"); return;
    }
    usb_printf("FLASHID %02X%02X%02X\n", id[0],id[1],id[2]);
}

void erase_flash_sector(uint32_t address, unsigned opcode) {
    unsigned size = opcode == 0xd7 ? 1024 : opcode == 0x20 ? 4096 : 0;
    if (!size || address > ITE_FLASH_MAX_SIZE-size || address % size) {
        usb_puts("ERR ERASESECTOR_ADDRESS"); return;
    }
    dbgr_hold_tick();
    if (!dbgr_hold_until_us) { usb_puts("ERR ERASESECTOR_NO_DBGR"); return; }
    const char *stage = "FOLLOW";
    if (!flash_follow()) goto failed;
    stage = "WRITE_ENABLE";
    if (!spi_short_command(0x06) || !spi_wait_status(3,2)) goto failed;
    stage = "ERASE_COMMAND";
    if (!spi_short_command(opcode)) goto failed;
    for (int shift=16; shift>=0; shift-=8)
        if (!dbgr_reg_write(0x08,(address>>shift)&255u)) goto failed;
    stage = "WAIT_READY";
    if (!spi_wait_status_for(1,0,10000000u) || !spi_short_command(0x04)) goto failed;
    dbgr_hold_refresh();
    usb_printf("ERASESECTOR %06lX OK\n", (unsigned long)address);
    return;
failed: {
        const char *reason = i2c_error ? i2c_error : "SPI_STATUS_ERROR";
        spi_short_command(0x04);
        usb_printf("ERR ERASESECTOR_%s ADDR=%06lX %s\n",stage,(unsigned long)address,reason);
    }
}

void program_flash_block(uint32_t address, const uint8_t *data,
                                size_t count) {
    const char *name = count == 256 ? "AAI256" : "AAI64";
    if (!dbgr_hold_until_us) { usb_printf("ERR %s_NO_DBGR\n", name); return; }
    if ((count != 64 && count != 256) ||
        address > ITE_FLASH_MAX_SIZE - count || (address & (count - 1u))) {
        usb_printf("ERR %s_ADDRESS\n", name); return;
    }
    const char *stage = "FOLLOW";
    bool quick_mode = false;
    spi_last_status = 0xff;
    dbgr_hold_tick();
    if (!dbgr_hold_until_us) { usb_printf("ERR %s_DBGR_HOLD_LOST\n", name); return; }
    const uint8_t follow[][2] = {
        {0x07, 0x7f}, {0x06, 0xff}, {0x05, 0xfe}, {0x04, 0}, {0x08, 0}
    };
    for (unsigned i = 0; i < sizeof follow / sizeof follow[0]; ++i) {
        if (!dbgr_reg_write(follow[i][0], follow[i][1])) goto failed;
    }
    stage = "WRITE_ENABLE";
    if (!spi_short_command(0x06) || !spi_wait_status(3, 2)) goto failed;
    dbgr_hold_tick();
    if (!dbgr_hold_until_us) { i2c_error = "DBGR_HOLD_LOST"; goto failed; }
    stage = "AAI_COMMAND";
    if (!spi_short_command(0xad)) goto failed;
    stage = "ADDRESS";
    for (int shift = 16; shift >= 0; shift -= 8) {
        uint8_t value = (address >> shift) & 0xffu;
        if (!write_i2c(0x35, &value, 1)) goto failed;
    }
    stage = "AAI_READY";
    if (!spi_wait_status(1, 0)) goto failed;
    stage = "QUICK_MODE";
    if (!dbgr_reg_write(0x10, 0x20)) goto failed;
    quick_mode = true;
    stage = "DATA";
    /* Chromium's legacy AAI writer keeps quick mode active across multiple
     * I2C block transfers. Four 64-byte transfers amortize WREN, address and
     * status setup without extending one I2C transaction beyond AAI64. */
    for (size_t offset = 0; offset < count; offset += 64) {
        if (!write_i2c(0x79, data + offset, 64)) goto failed;
    }
    stage = "FINISH";
    uint8_t finish = 0xff;
    if (!write_i2c(0x35, &finish, 1) ||
        !dbgr_reg_write(0x10, 0)) goto failed;
    quick_mode = false;
    stage = "WRITE_DISABLE";
    if (!spi_short_command(0x04) || !spi_wait_status(1, 0)) goto failed;
    dbgr_hold_refresh();
    usb_printf("%s %06lX OK\n", name, (unsigned long)address);
    return;
failed: {
        const char *reason = i2c_error ? i2c_error : "SPI_STATUS_ERROR";
        if (quick_mode) {
            uint8_t finish = 0xff;
            write_i2c(0x35, &finish, 1);
        }
        dbgr_reg_write(0x10, 0);
        spi_short_command(0x04);
        usb_printf("ERR %s_%s ADDR=%06lX STATUS=%02X %s\n", name,
               stage, (unsigned long)address, spi_last_status, reason);
    }
}

/* Newer IT8xxx 8315 eFlash sends the first AAI word through 0x35 before
 * quick block mode. KGD eFlash uses SPI page-program (0x02) instead. */
void program_flash_v2_block(uint32_t address, const uint8_t *data,
                                   size_t count, bool page_program) {
    const char *name = page_program ? "PAGE64" :
                       count == 256 ? "AAIV2_256" : "AAIV2_64";
    if (!dbgr_hold_until_us) { usb_printf("ERR %s_NO_DBGR\n", name); return; }
    if ((count != 64 && count != 256) || (page_program && count != 64) ||
        address > ITE_FLASH_MAX_SIZE - count || (address & (count - 1u))) {
        usb_printf("ERR %s_ADDRESS\n", name); return;
    }
    const char *stage = "FOLLOW";
    bool quick_mode = false;
    spi_last_status = 0xff;
    dbgr_hold_tick();
    if (!dbgr_hold_until_us) { usb_printf("ERR %s_DBGR_HOLD_LOST\n", name); return; }
    const uint8_t follow[][2] = {
        {0x07, 0x7f}, {0x06, 0xff}, {0x05, 0xfe}, {0x04, 0}, {0x08, 0}
    };
    for (unsigned i = 0; i < sizeof follow / sizeof follow[0]; ++i) {
        if (!dbgr_reg_write(follow[i][0], follow[i][1])) goto failed;
    }
    stage = "WRITE_ENABLE";
    if (!spi_short_command(0x06) || !spi_wait_status(3, 2)) goto failed;
    stage = "PROGRAM_COMMAND";
    if (!spi_short_command(page_program ? 0x02 : 0xad)) goto failed;
    stage = "ADDRESS";
    for (int shift = 16; shift >= 0; shift -= 8) {
        uint8_t value = (address >> shift) & 0xffu;
        if (!write_i2c(0x35, &value, 1)) goto failed;
    }
    if (page_program) {
        stage = "PAGE_DATA";
        if (!write_i2c(0x79, data, count)) goto failed;
    } else {
        stage = "FIRST_WORD";
        if (!write_i2c(0x35, data, 1) ||
            !write_i2c(0x35, data + 1, 1) ||
            !spi_wait_status(1, 0)) goto failed;
        stage = "QUICK_MODE";
        if (!dbgr_reg_write(0x10, 0x20)) goto failed;
        quick_mode = true;
        stage = "AAI_DATA";
        for (size_t offset = 2; offset < count; ) {
            size_t chunk = count - offset;
            if (chunk > 64) chunk = 64;
            if (!write_i2c(0x79, data + offset, chunk)) goto failed;
            offset += chunk;
        }
        stage = "FINISH";
        uint8_t finish = 0xff;
        if (!write_i2c(0x35, &finish, 1) ||
            !dbgr_reg_write(0x10, 0)) goto failed;
        quick_mode = false;
    }
    stage = "WAIT_READY";
    if (page_program) {
        if (!spi_wait_status(1, 0) || !spi_short_command(0x04)) goto failed;
    } else {
        if (!spi_short_command(0x04) || !spi_wait_status(1, 0)) goto failed;
    }
    dbgr_hold_refresh();
    usb_printf("%s %06lX OK\n", name, (unsigned long)address);
    return;
failed: {
        const char *reason = i2c_error ? i2c_error : "SPI_STATUS_ERROR";
        if (quick_mode) {
            uint8_t finish = 0xff;
            write_i2c(0x35, &finish, 1);
        }
        dbgr_reg_write(0x10, 0);
        spi_short_command(0x04);
        usb_printf("ERR %s_%s ADDR=%06lX STATUS=%02X %s\n", name,
               stage, (unsigned long)address, spi_last_status, reason);
    }
}

void read_flash_page(uint32_t address) {
    if (address > ITE_FLASH_MAX_SIZE - ITE_FLASH_PAGE_SIZE || address % ITE_FLASH_PAGE_SIZE) {
        usb_puts("ERR READPAGE_ADDRESS"); return;
    }
    static uint8_t page[ITE_FLASH_PAGE_SIZE];
    const uint8_t setup[][2] = {
        /* Keep watchdog alive, then issue only SPI FAST_READ (0x0B). */
        {0x2f, 0x1f}, {0x2e, 0x07}, {0x30, 0x5c},
        {0x07, 0x7f}, {0x06, 0xff}, {0x05, 0xfe},
        {0x04, 0}, {0x08, 0}, {0x05, 0xfd}, {0x08, 0x0b},
        {0x08, (address >> 16) & 0xffu},
        {0x08, (address >> 8) & 0xffu},
        {0x08, address & 0xffu}, {0x08, 0}
    };
    for (unsigned i = 0; i < sizeof setup / sizeof setup[0]; ++i) {
        if (!dbgr_reg_write(setup[i][0], setup[i][1])) {
            usb_printf("ERR READPAGE_SETUP_%u %s\n", i,
                   i2c_error ? i2c_error : "I2C_UNKNOWN");
            return;
        }
    }
    const uint8_t fast_read = 0x09;
    if (!write_i2c(0x5a, &fast_read, 1)) {
        usb_printf("ERR READPAGE_START %s\n",
               i2c_error ? i2c_error : "I2C_UNKNOWN");
        return;
    }
    if (!read_i2c(0x79, page, sizeof page)) {
        usb_printf("ERR READPAGE_DATA %s\n",
               i2c_error ? i2c_error : "I2C_UNKNOWN");
        return;
    }
    usb_printf("PAGE %06lX ", (unsigned long)address);
    for (unsigned i = 0; i < sizeof page; ++i) usb_printf("%02X", page[i]);
    usb_puts("");
    dbgr_hold_refresh();
}

