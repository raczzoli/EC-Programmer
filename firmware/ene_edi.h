/* SPDX-FileCopyrightText: 2026 R89 Repairs and contributors
 * SPDX-License-Identifier: GPL-2.0-or-later
 */
#ifndef ENE_EDI_H
#define ENE_EDI_H
#include <stdbool.h>
#include <stdint.h>

/* SPI0: GP4=MISO, GP5=CS, GP6=CLK, GP7=MOSI. */
bool ene_open(uint8_t *hwversion, uint8_t *ediid);
bool ene_open_family(const char *family, uint8_t *hwversion, uint8_t *ediid);
bool ene_close(void);
bool ene_is_open(void);
bool ene_read_page(uint32_t address, uint8_t data[128]);
bool ene_erase_page(uint32_t address);
bool ene_write_page(uint32_t address, const uint8_t data[128]);
const char *ene_error(void);
const uint8_t *ene_last_rx(void);
#endif
