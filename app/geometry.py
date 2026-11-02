# SPDX-FileCopyrightText: 2026 R89 Repairs and contributors
# SPDX-License-Identifier: GPL-2.0-or-later
"""ITE ranges implemented by the current page reader and programming commands."""
PAGE_SIZE = 256
FLASH_SIZES = tuple(kib * 1024 for kib in (64, 128, 192, 256))
MAX_FLASH_SIZE = max(FLASH_SIZES)
