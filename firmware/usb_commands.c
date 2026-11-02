/* SPDX-FileCopyrightText: 2026 R89 Repairs and contributors
 * SPDX-License-Identifier: GPL-2.0-or-later
 */
#include <stdio.h>
#include <string.h>
#include "ite_bus.h"
#include "ite_dbgr.h"
#include "ite_flash.h"
#include "ene_edi.h"
#include "usb_commands.h"
#include "usb_output.h"
#include "version.h"
#define MAX_XFER 64
#define MAX_PROGRAM 256
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
static void dispatch(char *cmd) {
    unsigned a, b; char hex[MAX_XFER*2+1]; uint8_t buf[MAX_XFER]; size_t len; int used;
    if (!strcmp(cmd,"HELLO")) { usb_puts("OK PICO_ITE_EC_PROGRAMMER 2"); return; }
    if (!strcmp(cmd,"CAPS")) { usb_puts("CAPS AAI64 AAI256 AAIV2_64 AAIV2_256 PAGE64 ENE_EDI TAGGED REGIO SPISTATUS FLASHID ERASESECTOR SESSION INFO I2CTIMING"); return; }
    if (!strcmp(cmd,"INFO")) {
        usb_printf("INFO VERSION=%s BUILD=%s BOARD=%s I2C_DELAY_US=%u\n",
                   EC_VERSION, EC_BUILD_ID, EC_BOARD, bus_timing());
        return;
    }
    if (!strncmp(cmd,"SYNC ",5)) { usb_printf("SYNC %s\n", cmd+5); return; }
    if (!strcmp(cmd,"ENDSESSION")) {
        dbgr_end_session();
        bool okay = ene_close();
        usb_puts(okay ? "OK" : "ERR ENE_CLOSE");
        return;
    }
    if (!strcmp(cmd,"ENERX")) {
        const uint8_t *rx = ene_last_rx();
        usb_printf("ENERX ");
        for (unsigned i=0; i<36; ++i) usb_printf("%02X", rx[i]);
        usb_puts("");
        return;
    }
    if (!strcmp(cmd,"RELEASE") || !strcmp(cmd,"ENECLOSE")) {
        bool okay = ene_close();
        release_bus();
        usb_puts(okay ? "OK" : "ERR ENE_CLOSE");
        return;
    }
    if (!strcmp(cmd,"ENEOPEN")) {
        uint8_t hw = 0, id = 0;
        if (!ene_is_open()) dbgr_end_session();
        if (!ene_open(&hw, &id)) {
            usb_printf("ERR %s HW=%02X EDI=%02X\n", ene_error(), hw, id);
            return;
        }
        usb_printf("ENEOPEN HW=%02X EDI=%02X\n", hw, id);
        return;
    }
    if ((sscanf(cmd,"ENEREADPAGE %8x%n",&a,&used)==1 && cmd[used] == 0)) {
        uint8_t page[128];
        if (!ene_read_page(a, page)) { usb_printf("ERR %s\n", ene_error()); return; }
        usb_printf("ENEPAGE %05X ", a);
        for (unsigned i=0; i<sizeof page; ++i) usb_printf("%02X", page[i]);
        usb_puts("");
        return;
    }
    if ((sscanf(cmd,"ENEERASEPAGE %8x%n",&a,&used)==1 && cmd[used] == 0)) {
        if (!ene_erase_page(a)) { usb_printf("ERR %s\n", ene_error()); return; }
        usb_printf("ENEERASEPAGE %05X OK\n", a);
        return;
    }
    if (!strncmp(cmd,"ENEWRITEPAGE ",13)) {
        char page_hex[257];
        uint8_t page[128];
        if ((sscanf(cmd,"ENEWRITEPAGE %8x %256s%n",&a,page_hex,&used)!=2 || cmd[used] != 0) ||
            !parse_hex(page_hex,page,sizeof page,&len) || len != sizeof page) {
            usb_puts("ERR ENEWRITEPAGE_DATA"); return;
        }
        if (!ene_write_page(a,page)) { usb_printf("ERR %s\n", ene_error()); return; }
        usb_printf("ENEWRITEPAGE %05X OK\n", a);
        return;
    }
    if (ene_is_open()) { usb_puts("ERR ENE_ACTIVE"); return; }
    if ((sscanf(cmd,"I2CTIMING %3u%n",&a,&used)==1 && cmd[used] == 0)) {
        usb_puts(bus_set_timing(a) ? "OK" : "ERR I2CTIMING"); return;
    }
    if ((sscanf(cmd,"REGREAD %8x%n",&a,&used)==1 && cmd[used] == 0)) {
        uint8_t value;
        if (a > 255) { usb_puts("ERR ARG"); return; }
        if (!dbgr_reg_read(a,&value)) usb_printf("ERR %s\n", i2c_error ? i2c_error : "REG_READ");
        else usb_printf("REG %02X %02X\n", a, value);
        return;
    }
    if ((sscanf(cmd,"REGWRITE %8x %8x%n",&a,&b,&used)==2 && cmd[used] == 0)) {
        if (a > 255 || b > 255) { usb_puts("ERR ARG"); return; }
        if (!dbgr_reg_write(a,b)) usb_printf("ERR %s\n", i2c_error ? i2c_error : "REG_WRITE");
        else usb_puts("OK");
        return;
    }
    if (!strcmp(cmd,"SESSION")) {
        uint8_t high, low, ver;
        if (!dbgr_reg_read(0x02,&ver) || !dbgr_reg_read(0x00,&high) ||
            !dbgr_reg_read(0x01,&low)) {
            usb_printf("ERR %s\n", i2c_error ? i2c_error : "SESSION_ID"); return;
        }
        if ((high & 0xf0u) != 0x80u) { usb_puts("ERR SESSION_ID"); return; }
        dbgr_hold_refresh();
        usb_printf("SESSION CHIPID=%02X%02X CHIPVER=%02X\n", high,low,ver);
        return;
    }
    if (!strcmp(cmd,"SPISTATUS")) { flash_status(); return; }
    if ((sscanf(cmd,"FLASHID %8x%n",&a,&used)==1 && cmd[used] == 0)) {
        if (a != 0x79 && a != 0x35) { usb_puts("ERR ARG"); return; }
        flash_identify(a); return;
    }
    if ((sscanf(cmd,"ERASESECTOR %8x %8x%n",&a,&b,&used)==2 && cmd[used] == 0)) {
        erase_flash_sector(a,b); return;
    }
    if (!strcmp(cmd,"HOLDDBGR")) {
        usb_printf("HOLDDBGR %s\n", dbgr_hold_until_us ? "ACTIVE" : "INACTIVE");
        return;
    }
    if (!strcmp(cmd,"ENTERDBGR")) { enter_dbgr_fast(); return; }
    if ((sscanf(cmd,"READPAGE %8x%n",&a,&used)==1 && cmd[used] == 0)) { read_flash_page(a); return; }
    if ((sscanf(cmd,"AAI64 %8x %128s%n",&a,hex,&used)==2 && cmd[used] == 0)) {
        if (!parse_hex(hex,buf,sizeof buf,&len) || len != 64) {
            usb_puts("ERR AAI64_DATA"); return;
        }
        program_flash_block(a,buf,64); return;
    }
    if ((sscanf(cmd,"AAIV2_64 %8x %128s%n",&a,hex,&used)==2 && cmd[used] == 0)) {
        if (!parse_hex(hex,buf,sizeof buf,&len) || len != 64) {
            usb_puts("ERR AAIV2_64_DATA"); return;
        }
        program_flash_v2_block(a,buf,64,false); return;
    }
    if (!strncmp(cmd,"AAIV2_256 ",10)) {
        char program_hex[MAX_PROGRAM*2+1];
        uint8_t program_data[MAX_PROGRAM];
        if ((sscanf(cmd,"AAIV2_256 %8x %512s%n",&a,program_hex,&used)!=2 || cmd[used] != 0) ||
            !parse_hex(program_hex,program_data,sizeof program_data,&len) ||
            len != MAX_PROGRAM) {
            usb_puts("ERR AAIV2_256_DATA"); return;
        }
        program_flash_v2_block(a,program_data,MAX_PROGRAM,false); return;
    }
    if ((sscanf(cmd,"PAGE64 %8x %128s%n",&a,hex,&used)==2 && cmd[used] == 0)) {
        if (!parse_hex(hex,buf,sizeof buf,&len) || len != 64) {
            usb_puts("ERR PAGE64_DATA"); return;
        }
        program_flash_v2_block(a,buf,64,true); return;
    }
    if (!strncmp(cmd,"AAI256 ",7)) {
        char program_hex[MAX_PROGRAM*2+1];
        uint8_t program_data[MAX_PROGRAM];
        if ((sscanf(cmd,"AAI256 %8x %512s%n",&a,program_hex,&used)!=2 || cmd[used] != 0) ||
            !parse_hex(program_hex,program_data,sizeof program_data,&len) ||
            len != MAX_PROGRAM) {
            usb_puts("ERR AAI256_DATA"); return;
        }
        program_flash_block(a,program_data,MAX_PROGRAM); return;
    }
    if (!strcmp(cmd,"WAVEPOWER")) { wave_at_power_on(); return; }
    if ((sscanf(cmd,"PINS %3u %3u%n",&a,&b,&used)==2 && cmd[used] == 0)) {
        if (!valid_pin(a)||!valid_pin(b)||a==b) { usb_puts("ERR PINS"); return; }
        if (a != sda_pin || b != scl_pin) {
            dbgr_hold_until_us = 0;
            wave_entry_rate = 0;
        }
        set_pins(a,b); usb_puts("OK"); return;
    }
    if (!strcmp(cmd,"WAVESWEEP")) {
        if (!adjacent_bus_pins()) { usb_puts("ERR NEED_CONSECUTIVE_PINS"); return; }
        static const unsigned rates[] = {200000, 300000, 400000, 500000, 600000, 800000};
        usb_printf("SWEEP");
        for (unsigned i = 0; i < sizeof rates / sizeof rates[0]; ++i) {
            waveform(false, rates[i]);
            bool ack = probe_write_address(0x5a);
            usb_printf(" %u:%s", rates[i], ack ? "ACK" : (i2c_error ? i2c_error : "ERROR"));
            if (ack) break;
        }
        usb_puts("");
        return;
    }
    if ((sscanf(cmd,"WRITE %8x %128s%n",&a,hex,&used)==2 && cmd[used] == 0)) {
        if (a>0x7f || !parse_hex(hex,buf,sizeof buf,&len)) { usb_puts("ERR ARG"); return; }
        if (write_i2c(a,buf,len)) usb_puts("OK");
        else usb_printf("ERR %s\n", i2c_error ? i2c_error : "I2C_UNKNOWN");
        return;
    }
    if ((sscanf(cmd,"READ %8x %3u%n",&a,&b,&used)==2 && cmd[used] == 0)) {
        if (a>0x7f || b<1 || b>MAX_XFER) { usb_puts("ERR ARG"); return; }
        if (!read_i2c(a,buf,b)) {
            usb_printf("ERR %s\n", i2c_error ? i2c_error : "I2C_UNKNOWN");
            return;
        }
        usb_printf("DATA "); for (uint i=0;i<b;++i) usb_printf("%02X",buf[i]); usb_puts(""); return;
    }
    usb_puts("ERR COMMAND");
}

void usb_command(char *cmd) {
    uint32_t tag = 0;
    bool tagged = cmd[0] == '@';
    if (tagged) {
        if (strlen(cmd) < 11 || cmd[9] != ' ') {
            usb_reply_begin(false,0); usb_puts("ERR TAG"); return;
        }
        for (unsigned i=1; i<=8; ++i) {
            int digit = hex_digit(cmd[i]);
            if (digit < 0) { usb_reply_begin(false,0); usb_puts("ERR TAG"); return; }
            tag = (tag << 4) | (unsigned)digit;
        }
        cmd += 10;
    }
    usb_reply_begin(tagged,tag);
    /* A command cannot occupy the bus indefinitely. Host timeouts exceed
     * this budget; WAVEPOWER has its own 40-second reset window. */
    unsigned budget = 3000;
    if (!strcmp(cmd,"WAVEPOWER")) budget = 45000;
    else if (!strcmp(cmd,"ENTERDBGR") || !strcmp(cmd,"WAVESWEEP")) budget = 5000;
    else if (!strncmp(cmd,"AAI",3) || !strncmp(cmd,"PAGE64 ",7) ||
             !strncmp(cmd,"ERASESECTOR ",12)) budget = 20000;
    bus_set_deadline(budget);
    dispatch(cmd);
    bus_set_deadline(0);
}
