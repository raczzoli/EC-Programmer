/* SPDX-FileCopyrightText: 2026 R89 Repairs and contributors
 * SPDX-License-Identifier: GPL-2.0-or-later
 */
/* Runs production ITE flash/session/parser code against a recording bus. */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "ite_bus.h"
#include "ite_dbgr.h"
#include "ite_flash.h"
#include "ene_edi.h"
#include "usb_commands.h"
#include "line_reader.h"

uint sda_pin=7, scl_pin=6;
const char *i2c_error;
unsigned wave_entry_rate;
static uint64_t now;
static unsigned writes, fail_at, timing=5;
static uint8_t cursor=8;
uint64_t time_us_64(void) { return ++now; }
void sleep_us(uint64_t us) { now+=us; }
bool write_i2c(uint8_t address,const uint8_t *data,size_t count) {
    printf("W %02X ",address);
    for (size_t i=0;i<count;++i) printf("%02X",data[i]);
    puts("");
    if (++writes == fail_at) { i2c_error="INJECTED_NACK"; return false; }
    if (address==0x5a && count==1) cursor=data[0];
    return true;
}
bool read_i2c(uint8_t address,uint8_t *data,size_t count) {
    printf("R %02X %u\n",address,(unsigned)count);
    for (size_t i=0;i<count;++i) data[i]=address==0x79 ? (uint8_t)i : 2;
    return true;
}
bool dbgr_reg_write(uint8_t reg,uint8_t value) {
    return write_i2c(0x5a,&reg,1) && write_i2c(0x35,&value,1);
}
bool dbgr_reg_read(uint8_t reg,uint8_t *value) {
    return write_i2c(0x5a,&reg,1) && read_i2c(0x35,value,1);
}
bool bus_selected_register(uint8_t *reg) { *reg=cursor; return true; }
void release_bus(void) {}
void release_pin(uint p) { (void)p; }
void low_pin(uint p) { (void)p; }
void set_pins(uint sda,uint scl) { sda_pin=sda; scl_pin=scl; }
bool valid_pin(uint p) { return p<=22 || (p>=26 && p<=28); }
bool adjacent_bus_pins(void) { return sda_pin+1==scl_pin || scl_pin+1==sda_pin; }
bool probe_write_address(uint8_t p) { (void)p; return true; }
void bus_set_deadline(unsigned ms) { (void)ms; }
bool bus_set_timing(unsigned us) { if(us!=5 && us!=3 && us!=2) return false; timing=us; return true; }
unsigned bus_timing(void) { return timing; }
void waveform(bool settle,unsigned frequency) { (void)settle; (void)frequency; }
void wave_at_power_on(void) {}
void enter_dbgr_fast(void) {}
bool ene_open(uint8_t *hw,uint8_t *id) { *hw=0; *id=0; return false; }
bool ene_close(void) { return true; }
bool ene_is_open(void) { return false; }
bool ene_read_page(uint32_t a,uint8_t d[128]) { (void)a;(void)d;return false; }
bool ene_erase_page(uint32_t a) { (void)a;return false; }
bool ene_write_page(uint32_t a,const uint8_t d[128]) { (void)a;(void)d;return false; }
const char *ene_error(void) { return "SIMULATED"; }
const uint8_t *ene_last_rx(void) { static uint8_t d[36]; return d; }

int main(int argc,char **argv) {
    if(argc<2) return 2;
    uint8_t data[256];
    for(unsigned i=0;i<256;++i) data[i]=(uint8_t)i;
    dbgr_hold_until_us=30000000;
    dbgr_next_feed_us=1000000;
    if(argc>2 && strcmp(argv[1],"command")) fail_at=(unsigned)atoi(argv[2]);
    if(!strcmp(argv[1],"legacy64")) program_flash_block(0x100,data,64);
    else if(!strcmp(argv[1],"legacy256")) program_flash_block(0x100,data,256);
    else if(!strcmp(argv[1],"v2_64")) program_flash_v2_block(0x100,data,64,false);
    else if(!strcmp(argv[1],"v2_256")) program_flash_v2_block(0x100,data,256,false);
    else if(!strcmp(argv[1],"page64")) program_flash_v2_block(0x100,data,64,true);
    else if(!strcmp(argv[1],"read")) read_flash_page(0x100);
    else if(!strcmp(argv[1],"hold")) {
        dbgr_next_feed_us=0;
        dbgr_hold_tick();
        printf("CURSOR=%02X HOLD=%u\n",cursor,dbgr_hold_until_us!=0);
    }
#ifndef BASELINE
    else if(!strcmp(argv[1],"erase1k")) erase_flash_sector(0x400,0xd7);
    else if(!strcmp(argv[1],"erase4k")) erase_flash_sector(0x1000,0x20);
    else if(!strcmp(argv[1],"command") && argc>2) usb_command(argv[2]);
    else if(!strcmp(argv[1],"overflow")) {
        command_buffer buffer={0};
        for(unsigned i=0;i<MAX_LINE+5;++i) if(command_feed(&buffer,'X')<0) puts("OVERFLOW");
        const char *tail="WRITE 35 AD\nHELLO\n";
        for(const char *p=tail;*p;++p) if(command_feed(&buffer,*p)>0) usb_command(buffer.text);
    }
#endif
    else return 3;
    return 0;
}
