/* SPDX-FileCopyrightText: 2026 R89 Repairs and contributors
 * SPDX-License-Identifier: GPL-2.0-or-later
 */
#pragma once
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#define ITE_FLASH_MAX_SIZE (256u * 1024u)
#define ITE_FLASH_PAGE_SIZE 256u
void program_flash_block(uint32_t address, const uint8_t *data, size_t count);
void program_flash_v2_block(uint32_t address, const uint8_t *data, size_t count, bool page_program);
void read_flash_page(uint32_t address);
void flash_status(void);
void flash_identify(uint8_t port);
void erase_flash_sector(uint32_t address, unsigned opcode);
