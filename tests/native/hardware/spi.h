/* SPDX-FileCopyrightText: 2026 R89 Repairs and contributors
 * SPDX-License-Identifier: GPL-2.0-or-later
 */
#pragma once
#include <stdint.h>
#include <stddef.h>
typedef struct { int unused; } spi_inst_t;
extern spi_inst_t *spi0;
#define SPI_CPOL_0 0
#define SPI_CPHA_0 0
#define SPI_MSB_FIRST 0
unsigned spi_init(spi_inst_t *spi, unsigned baud);
void spi_deinit(spi_inst_t *spi);
void spi_set_format(spi_inst_t *spi, unsigned bits, unsigned cpol, unsigned cpha, unsigned order);
int spi_write_blocking(spi_inst_t *spi, const uint8_t *src, size_t len);
int spi_write_read_blocking(spi_inst_t *spi, const uint8_t *src, uint8_t *dst, size_t len);
