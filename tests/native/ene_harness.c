/* SPDX-FileCopyrightText: 2026 R89 Repairs and contributors
 * SPDX-License-Identifier: GPL-2.0-or-later
 */
/* Register-level EC simulator: executes production ene_edi.c, no USB device.
 * Models EDI framing, reset, flash latch/program/erase and injected faults.
 */
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "pico/stdlib.h"
#include "hardware/spi.h"
#include "ene_edi.h"

static spi_inst_t instance;
spi_inst_t *spi0 = &instance;
static uint8_t regs[65536], flash[160*1024], latch[128];
static uint64_t now;
static unsigned output_mask, functions[8], reads, reset_writes, wdt_writes;
static unsigned flash_commands, latches, erases, programs, release_attempts;
static bool initialized, cs_high = true, busy;
static const char *fault;
static bool is(const char *name) { return !strcmp(fault,name); }
uint64_t time_us_64(void) { return ++now; }
void sleep_us(uint64_t us) { now += us; }
absolute_time_t make_timeout_time_ms(uint32_t ms) { return now + (uint64_t)ms*1000; }
bool time_reached(absolute_time_t deadline) { return now >= deadline; }
void gpio_init(unsigned pin) { assert(pin==5); functions[pin]=GPIO_FUNC_SIO; }
void gpio_put(unsigned pin,bool value) { assert(pin==5); cs_high=value; }
void gpio_set_dir(unsigned pin,bool output) {
    assert(pin>=4 && pin<=7);
    if(output) output_mask|=1u<<pin; else output_mask&=~(1u<<pin);
}
void gpio_set_function(unsigned pin,unsigned function) { assert(pin>=4 && pin<=7); functions[pin]=function; }
unsigned spi_init(spi_inst_t *spi,unsigned baud) { assert(spi==spi0 && baud==2000000); initialized=true; return baud; }
void spi_deinit(spi_inst_t *spi) { assert(spi==spi0); initialized=false; }
void spi_set_format(spi_inst_t *spi,unsigned bits,unsigned cpol,unsigned cpha,unsigned order) {
    assert(spi==spi0 && bits==8 && !cpol && !cpha && !order);
}
static uint32_t address(void) { return regs[0xfea8] | ((uint32_t)regs[0xfea9]<<8) | ((uint32_t)regs[0xfeaa]<<16); }
int spi_write_blocking(spi_inst_t *spi,const uint8_t *src,size_t len) {
    assert(spi==spi0 && initialized && !cs_high);
    now+=100;
    if(len==1) { assert(src[0]==0xf3); return 1; }
    assert(len==5 && src[0]==0x40 && src[1]==0);
    uint16_t reg=(uint16_t)((src[2]<<8)|src[3]);
    uint8_t value=src[4];
    if(reg==0xff14) {
        ++reset_writes;
        if(value&1) { if(is("resetfail")) return 5; }
        else { ++release_attempts; if(is("closefail")) return 5; }
    }
    if(reg==0xfe80) { ++wdt_writes; if(is("wdtfail")) return -1; }
    regs[reg]=value;
    if(reg==0xfeac) {
        ++flash_commands;
        uint32_t addr=address();
        assert(addr<sizeof flash);
        /* Real targets may ignore commands after an asynchronous reset. */
        if(!(regs[0xff14]&1) || !(regs[0xfead]&8)) return 5;
        if(value==0x03) {
            regs[0xfeab]=flash[addr];
            if(is("midreset")) { regs[0xff14]&=~1u; regs[0xfead]=0; }
        } else if(value==0x20) {
            assert(!(addr%128)); memset(flash+addr,0,128); ++erases; busy=is("busy");
        } else if(value==0x80) {
            memset(latch,0,128); latches=0;
        } else if(value==0x02) {
            assert(addr%128==latches); latch[latches++]=regs[0xfeab];
        } else if(value==0x70) {
            assert(latches==128 && addr%128==127);
            memcpy(flash+(addr&~127u),latch,128); ++programs;
        } else assert(false);
    }
    return 5;
}
int spi_write_read_blocking(spi_inst_t *spi,const uint8_t *src,uint8_t *dst,size_t len) {
    assert(spi==spi0 && initialized && !cs_high);
    assert(len==36 && src[0]==0x30 && src[1]==0);
    for(size_t i=4;i<len;++i) assert(src[i]==0xff);
    now+=100; ++reads;
    uint16_t reg=(uint16_t)((src[2]<<8)|src[3]);
    memset(dst,0x5f,len);
    if(is("short")) return (int)len-1;
    if(is("notready")) return (int)len;
    if(is("noise")) { dst[4]=0xaa; dst[5]=0x50; dst[6]=regs[reg]; return (int)len; }
    if(is("late") && reads<=12) { memset(dst,0,len); return (int)len; }
    if(is("ready_tail") && reads<=9) { dst[35]=0x50; return (int)len; }
    unsigned ready=is("delayed") ? 34 : 6;
    dst[ready]=0x50;
    dst[ready+1]=regs[reg] | ((reg==0xfead && busy) ? 2 : 0);
    return (int)len;
}
static void released(void) {
    assert(!initialized && output_mask==0 && !ene_is_open());
    for(unsigned i=4;i<=7;++i) assert(functions[i]==GPIO_FUNC_SIO);
}
int main(int argc,char **argv) {
    if(argc<5) return 2;
    const char *family=argv[1];
    regs[0xff00]=(uint8_t)strtoul(argv[2],NULL,16);
    regs[0xff24]=(uint8_t)strtoul(argv[3],NULL,16);
    fault=argv[4];
    memset(flash,0xa5,sizeof flash);
    uint8_t hw=0,id=0,data[128],expected[128];
    if(!ene_open_family(family,&hw,&id)) {
        printf("OPEN_ERROR %s RESET=%u WDT=%u CPU=%u\n",ene_error(),reset_writes,wdt_writes,regs[0xff14]&1);
        released(); return 0;
    }
    assert(hw==regs[0xff00] && id==regs[0xff24]);
    printf("OPEN %02X/%02X WDT=%u VALUE=%02X\n",hw,id,wdt_writes,regs[0xfe80]);
    unsigned capacity=argc>5 ? (unsigned)strtoul(argv[5],NULL,0) : 128*1024;
    unsigned before=flash_commands;
    if(is("lost")) {
        regs[0xff14]=0;
        assert(!ene_read_page(0,data) && !strcmp(ene_error(),"EDI_SESSION_LOST"));
        assert(!ene_erase_page(0) && !ene_write_page(0,data));
        assert(flash_commands==before); puts("SESSION_LOST_BEFORE_FLASH");
    } else if(is("midreset")) {
        assert(!ene_read_page(0,data) && !strcmp(ene_error(),"EDI_SESSION_LOST"));
        puts("SESSION_LOST_DURING_READ");
    } else if(is("busy")) {
        assert(!ene_erase_page(0) && !strcmp(ene_error(),"EDI_FLASH_BUSY_TIMEOUT"));
        assert(!(regs[0xfead]&8)); puts("BUSY_TIMEOUT_WRITE_DISABLED");
    } else if(is("idchange")) {
        regs[0xff00]^=1;
        assert(!ene_open_family(family,&hw,&id) && !strcmp(ene_error(),"EDI_ID_CHANGED"));
        assert(flash_commands==before); puts("ID_CHANGED");
    } else if(!is("closefail")) {
        const unsigned addresses[]={0,0xff80,0x10000,capacity-128};
        for(unsigned n=0;n<sizeof addresses/sizeof addresses[0];++n) {
            unsigned addr=addresses[n];
            uint8_t neighbor=addr ? flash[addr-1] : flash[128];
            assert(ene_erase_page(addr));
            assert(ene_read_page(addr,data));
            for(unsigned i=0;i<128;++i) {
                assert(data[i]==0); expected[i]=(uint8_t)(i*17+3);
            }
            assert(ene_write_page(addr,expected));
            assert(ene_read_page(addr,data) && !memcmp(data,expected,128));
            assert((addr ? flash[addr-1] : flash[128])==neighbor);
            assert(!(regs[0xfead]&8));
        }
        before=flash_commands;
        const unsigned invalid[]={1,capacity,0xffffffff};
        for(unsigned i=0;i<sizeof invalid/sizeof invalid[0];++i) {
            assert(!ene_read_page(invalid[i],data));
            assert(!ene_erase_page(invalid[i]));
            assert(!ene_write_page(invalid[i],data));
        }
        assert(flash_commands==before);
        printf("ROUNDTRIP %u ERASES=%u PROGRAMS=%u BOUNDS_OK\n",capacity,erases,programs);
    }
    bool okay=ene_close();
    released();
    assert(okay!=is("closefail"));
    if(!is("closefail")) assert(!(regs[0xff14]&1));
    printf("CLOSE=%u PINS_RELEASED\n",okay);
    return 0;
}
