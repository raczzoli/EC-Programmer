/* SPDX-FileCopyrightText: 2026 R89 Repairs and contributors
 * SPDX-License-Identifier: GPL-2.0-or-later
 */
/* Experimental USB CDC bridge for probing.
 * All external GPIO transitions are open-drain: output LOW or input/Hi-Z.
 */
#include <stdio.h>
#include <stdint.h>
#include <string.h>
#include <stdlib.h>
#include "pico/stdlib.h"
#include "hardware/gpio.h"
#include "hardware/pio.h"
#include "hardware/dma.h"
#include "hardware/clocks.h"
#include "dbgr_open_drain.pio.h"

#define MAX_LINE 544
#define MAX_XFER 64
#define MAX_PROGRAM 256
#define CLOCK_TIMEOUT_US 25000
static uint sda_pin = 7, scl_pin = 6;
static char line[MAX_LINE];
static const char *i2c_error;
static uint64_t dbgr_hold_until_us;
static uint64_t dbgr_next_feed_us;
static unsigned wave_entry_rate;
static uint8_t spi_last_status;

static void release_pin(uint pin) { gpio_set_dir(pin, GPIO_IN); }
static void low_pin(uint pin) { gpio_put(pin, 0); gpio_set_dir(pin, GPIO_OUT); }
static void release_bus(void) { release_pin(sda_pin); release_pin(scl_pin); }
static bool clock_high(void) {
    release_pin(scl_pin);
    absolute_time_t end = make_timeout_time_us(CLOCK_TIMEOUT_US);
    while (!gpio_get(scl_pin)) if (time_reached(end)) {
        i2c_error = "SCL_LOW_TIMEOUT";
        return false;
    }
    sleep_us(5);
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
    if (value) release_pin(sda_pin); else low_pin(sda_pin);
    sleep_us(5);
    if (!clock_high()) return false;
    low_pin(scl_pin); sleep_us(5); return true;
}
static bool bit_in(bool *value) {
    release_pin(sda_pin); sleep_us(5);
    if (!clock_high()) return false;
    *value = gpio_get(sda_pin);
    low_pin(scl_pin); sleep_us(5); return true;
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
static bool write_i2c(uint8_t addr, const uint8_t *buf, size_t len) {
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
    stop(); return ok;
}
static bool probe_write_address(uint8_t addr) {
    i2c_error = NULL;
    bool ok = start();
    if (ok && !byte_out(addr << 1)) {
        if (!i2c_error) i2c_error = "ADDRESS_NACK";
        ok = false;
    }
    stop();
    return ok;
}
static bool read_i2c(uint8_t addr, uint8_t *buf, size_t len) {
    i2c_error = NULL;
    bool ok = start();
    if (ok && !byte_out((addr << 1) | 1)) {
        if (!i2c_error) i2c_error = "ADDRESS_NACK";
        ok = false;
    }
    for (size_t i = 0; ok && i < len; ++i) ok = byte_in(&buf[i], i + 1 < len);
    stop(); return ok;
}
static void set_pins(uint sda, uint scl) {
    release_bus(); sda_pin = sda; scl_pin = scl;
    gpio_init(sda_pin); gpio_init(scl_pin);
    gpio_disable_pulls(sda_pin); gpio_disable_pulls(scl_pin);
    gpio_put(sda_pin, 0); gpio_put(scl_pin, 0); release_bus();
}
static bool valid_pin(uint p) { return p <= 22 || (p >= 26 && p <= 28); }
static bool adjacent_bus_pins(void) {
    return scl_pin == sda_pin + 1 || sda_pin == scl_pin + 1;
}
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
 * PIO uses consecutive pins: bit0=SDA, bit1=SCL.
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
    sleep_us(25); /* allow the final 16 states in OSR to complete */
    pio_sm_set_enabled(pio, sm, false);
    release_bus(); /* preset SIO directions before changing GPIO function */
    gpio_set_function(sda_pin, GPIO_FUNC_SIO);
    gpio_set_function(scl_pin, GPIO_FUNC_SIO);
    dma_channel_unclaim(dma);
    pio_sm_unclaim(pio, sm);
    pio_remove_program(pio, &dbgr_open_drain_program, offset);
    if (settle) sleep_ms(10);
}

static void waveform(bool settle, unsigned frequency) {
    if (adjacent_bus_pins()) waveform_pio(settle, frequency);
    else waveform_soft(settle);
}

static void wave_at_power_on(void) {
    release_bus();
    puts("READY WAVEPOWER WAIT_POWER_OFF");
    absolute_time_t timeout = make_timeout_time_ms(40000);
    uint64_t low_since = 0;
    while (!time_reached(timeout)) {
        if (!gpio_get(scl_pin)) {
            if (!low_since) low_since = time_us_64();
            if (time_us_64() - low_since >= 100000u) break;
        } else low_since = 0;
        sleep_ms(1);
    }
    if (time_reached(timeout)) { puts("ERR WAVEPOWER_NO_POWER_OFF"); return; }
    puts("POWER_OFF_DETECTED WAIT_POWER_ON");
    while (!gpio_get(scl_pin) && !time_reached(timeout)) tight_loop_contents();
    if (time_reached(timeout)) { puts("ERR WAVEPOWER_NO_POWER_ON"); return; }
    static const unsigned rates[] = {800000, 600000, 400000, 300000};
    wave_entry_rate = 0;
    for (unsigned i = 0; i < sizeof rates / sizeof rates[0]; ++i) {
        waveform(false, rates[i]);
        /* Select DBGR immediately while the entry window is open. */
        uint8_t reg = 0x07, value = 0x7f;
        if (write_i2c(0x5a, &reg, 1) && write_i2c(0x35, &value, 1)) {
            wave_entry_rate = rates[i];
            printf("WAVEPOWER %u ADDRESS_ACK\n", rates[i]);
            return;
        }
    }
    printf("WAVEPOWER 0 %s\n", i2c_error ? i2c_error : "I2C_UNKNOWN");
}

static bool dbgr_reg_write(uint8_t reg, uint8_t value) {
    return write_i2c(0x5a, &reg, 1) && write_i2c(0x35, &value, 1);
}

static bool dbgr_reg_read(uint8_t reg, uint8_t *value) {
    return write_i2c(0x5a, &reg, 1) && read_i2c(0x35, value, 1);
}

/* The EC tested here reports WDT=5A, rather than Chromium's disabled value
 * 30, and loses DBGR after a brief idle period. Feed only after a successful
 * DBGR entry; expire the hold automatically after 30 seconds without a read.
 */
static void dbgr_hold_refresh(void) {
    dbgr_hold_until_us = time_us_64() + 30000000u;
    dbgr_next_feed_us = time_us_64() + 10000u;
}

static void dbgr_hold_tick(void) {
    if (!dbgr_hold_until_us) return;
    uint64_t now = time_us_64();
    if (now >= dbgr_hold_until_us) {
        dbgr_hold_until_us = 0;
        return;
    }
    if (now < dbgr_next_feed_us) return;
    if (!dbgr_reg_write(0x2f, 0x1f) ||
        !dbgr_reg_write(0x2e, 0x07) ||
        !dbgr_reg_write(0x30, 0x5c)) {
        dbgr_hold_until_us = 0;
        return;
    }
    dbgr_next_feed_us = time_us_64() + 10000u;
}

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

static bool spi_wait_status(uint8_t mask, uint8_t expected) {
    if (!spi_short_command(0x05)) return false;
    uint64_t deadline = time_us_64() + 5000000u;
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

static void program_flash_block(uint32_t address, const uint8_t *data,
                                size_t count) {
    const char *name = count == 256 ? "AAI256" : "AAI64";
    if (!dbgr_hold_until_us) { printf("ERR %s_NO_DBGR\n", name); return; }
    if (address > 0x40000u - count || (address & (count - 1u))) {
        printf("ERR %s_ADDRESS\n", name); return;
    }
    const char *stage = "FOLLOW";
    bool quick_mode = false;
    spi_last_status = 0xff;
    dbgr_hold_tick();
    if (!dbgr_hold_until_us) { printf("ERR %s_DBGR_HOLD_LOST\n", name); return; }
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
    printf("%s %06lX OK\n", name, (unsigned long)address);
    return;
failed: {
        const char *reason = i2c_error ? i2c_error : "SPI_STATUS_ERROR";
        if (quick_mode) {
            uint8_t finish = 0xff;
            write_i2c(0x35, &finish, 1);
        }
        dbgr_reg_write(0x10, 0);
        spi_short_command(0x04);
        printf("ERR %s_%s ADDR=%06lX STATUS=%02X %s\n", name,
               stage, (unsigned long)address, spi_last_status, reason);
    }
}

static void enter_dbgr_fast(void) {
    dbgr_hold_until_us = 0;
    if (!adjacent_bus_pins()) { puts("ERR ENTERDBGR_PINS"); return; }
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
        printf("ERR ENTERDBGR_NO_ACK %s\n",
               i2c_error ? i2c_error : "I2C_UNKNOWN");
        return;
    }
    static const uint8_t stop_sequence[][2] = {
        {0x06, 0xff}, {0x05, 0xfe}, {0x04, 0}, {0x08, 0},
        {0x07, 0}, {0x06, 0}
    };
    for (unsigned i = 0; i < sizeof stop_sequence / sizeof stop_sequence[0]; ++i) {
        if (!dbgr_reg_write(stop_sequence[i][0], stop_sequence[i][1])) {
            printf("ERR ENTERDBGR_STOP_%u %s\n", i,
                   i2c_error ? i2c_error : "I2C_UNKNOWN");
            return;
        }
    }
    uint8_t ver, high, low;
    if (!dbgr_reg_read(0x02, &ver) ||
        !dbgr_reg_read(0x00, &high) ||
        !dbgr_reg_read(0x01, &low)) {
        printf("ERR ENTERDBGR_ID %s\n",
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
            printf("ERR ENTERDBGR_WDT_%u %s\n", i,
                   i2c_error ? i2c_error : "I2C_UNKNOWN");
            return;
        }
    }
    sleep_ms(1);
    if (!dbgr_reg_write(0x30, 0x30)) {
        printf("ERR ENTERDBGR_WDT_FINAL %s\n",
               i2c_error ? i2c_error : "I2C_UNKNOWN");
        return;
    }
    sleep_ms(1);
    uint8_t watchdog;
    if (!dbgr_reg_write(0x2f, 0x1f) ||
        !dbgr_reg_write(0x2e, 0x05) ||
        !dbgr_reg_read(0x30, &watchdog)) {
        printf("ERR ENTERDBGR_WDT_READ %s\n",
               i2c_error ? i2c_error : "I2C_UNKNOWN");
        return;
    }
    printf("ENTERDBGR RATE=%u CHIPID=%02X%02X CHIPVER=%02X WDT=%02X\n",
           selected_rate, high, low, ver, watchdog);
    dbgr_hold_refresh();
}

static void read_flash_page(uint32_t address) {
    if (address > 0x3ff00u || (address & 0xffu)) {
        puts("ERR READPAGE_ADDRESS"); return;
    }
    static uint8_t page[256];
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
            printf("ERR READPAGE_SETUP_%u %s\n", i,
                   i2c_error ? i2c_error : "I2C_UNKNOWN");
            return;
        }
    }
    const uint8_t fast_read = 0x09;
    if (!write_i2c(0x5a, &fast_read, 1)) {
        printf("ERR READPAGE_START %s\n",
               i2c_error ? i2c_error : "I2C_UNKNOWN");
        return;
    }
    if (!read_i2c(0x79, page, sizeof page)) {
        printf("ERR READPAGE_DATA %s\n",
               i2c_error ? i2c_error : "I2C_UNKNOWN");
        return;
    }
    printf("PAGE %06lX ", (unsigned long)address);
    for (unsigned i = 0; i < sizeof page; ++i) printf("%02X", page[i]);
    puts("");
    dbgr_hold_refresh();
}

static int hex_digit(char c) {
    if (c >= '0' && c <= '9') return c-'0';
    if (c >= 'A' && c <= 'F') return c-'A'+10;
    if (c >= 'a' && c <= 'f') return c-'a'+10;
    return -1;
}
static bool parse_hex(const char *s, uint8_t *buf, size_t capacity, size_t *len) {
    size_t n = strlen(s);
    if (!n || (n & 1) || n > capacity*2) return false;
    for (size_t i=0; i<n; i+=2) {
        int h=hex_digit(s[i]), l=hex_digit(s[i+1]);
        if (h<0 || l<0) return false;
        buf[i/2]=(uint8_t)((h<<4)|l);
    }
    *len=n/2; return true;
}
static void command(char *cmd) {
    unsigned a, b; char hex[MAX_XFER*2+1]; uint8_t buf[MAX_XFER]; size_t len;
    if (!strcmp(cmd,"HELLO")) { puts("OK PICO_ITE_EC_PROGRAMMER 2"); return; }
    if (!strcmp(cmd,"CAPS")) { puts("CAPS AAI64 AAI256"); return; }
    if (!strcmp(cmd,"RELEASE")) { release_bus(); puts("OK"); return; }
    if (!strcmp(cmd,"HOLDDBGR")) {
        printf("HOLDDBGR %s\n", dbgr_hold_until_us ? "ACTIVE" : "INACTIVE");
        return;
    }
    if (!strcmp(cmd,"ENTERDBGR")) { enter_dbgr_fast(); return; }
    if (sscanf(cmd,"READPAGE %x",&a)==1) { read_flash_page(a); return; }
    if (sscanf(cmd,"AAI64 %x %128s",&a,hex)==2) {
        if (!parse_hex(hex,buf,sizeof buf,&len) || len != 64) {
            puts("ERR AAI64_DATA"); return;
        }
        program_flash_block(a,buf,64); return;
    }
    if (!strncmp(cmd,"AAI256 ",7)) {
        char program_hex[MAX_PROGRAM*2+1];
        uint8_t program_data[MAX_PROGRAM];
        if (sscanf(cmd,"AAI256 %x %512s",&a,program_hex)!=2 ||
            !parse_hex(program_hex,program_data,sizeof program_data,&len) ||
            len != MAX_PROGRAM) {
            puts("ERR AAI256_DATA"); return;
        }
        program_flash_block(a,program_data,MAX_PROGRAM); return;
    }
    if (!strcmp(cmd,"WAVEPOWER")) { wave_at_power_on(); return; }
    if (sscanf(cmd,"PINS %u %u",&a,&b)==2) {
        if (!valid_pin(a)||!valid_pin(b)||a==b) { puts("ERR PINS"); return; }
        if (a != sda_pin || b != scl_pin) {
            dbgr_hold_until_us = 0;
            wave_entry_rate = 0;
        }
        set_pins(a,b); puts("OK"); return;
    }
    if (!strcmp(cmd,"WAVESWEEP")) {
        if (!adjacent_bus_pins()) { puts("ERR NEED_CONSECUTIVE_PINS"); return; }
        static const unsigned rates[] = {200000, 300000, 400000, 500000, 600000, 800000};
        printf("SWEEP");
        for (unsigned i = 0; i < sizeof rates / sizeof rates[0]; ++i) {
            waveform(false, rates[i]);
            bool ack = probe_write_address(0x5a);
            printf(" %u:%s", rates[i], ack ? "ACK" : (i2c_error ? i2c_error : "ERROR"));
            if (ack) break;
        }
        puts("");
        return;
    }
    if (sscanf(cmd,"WRITE %x %128s",&a,hex)==2) {
        if (a>0x7f || !parse_hex(hex,buf,sizeof buf,&len)) { puts("ERR ARG"); return; }
        if (write_i2c(a,buf,len)) puts("OK");
        else printf("ERR %s\n", i2c_error ? i2c_error : "I2C_UNKNOWN");
        return;
    }
    if (sscanf(cmd,"READ %x %u",&a,&b)==2) {
        if (a>0x7f || b<1 || b>MAX_XFER) { puts("ERR ARG"); return; }
        if (!read_i2c(a,buf,b)) {
            printf("ERR %s\n", i2c_error ? i2c_error : "I2C_UNKNOWN");
            return;
        }
        printf("DATA "); for (uint i=0;i<b;++i) printf("%02X",buf[i]); puts(""); return;
    }
    puts("ERR COMMAND");
}
int main(void) {
    stdio_init_all(); set_pins(7,6);
    size_t n=0;
    while (true) {
        int c=getchar_timeout_us(5000);
        if (c==PICO_ERROR_TIMEOUT) { dbgr_hold_tick(); continue; }
        if (c=='\n' || c=='\r') {
            if (n) { line[n]=0; command(line); n=0; }
        } else if (c>=32 && c<127) {
            if (n+1<sizeof line) line[n++]=(char)c;
            else { n=0; release_bus(); puts("ERR LINE_TOO_LONG"); }
        }
    }
}
