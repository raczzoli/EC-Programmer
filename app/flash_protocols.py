# SPDX-FileCopyrightText: 2026 R89 Repairs and contributors
# SPDX-License-Identifier: GPL-2.0-or-later

"""Recognize ITE IT8xxx flash command sets from live protocol responses.

These are command signatures and algorithms, not a whitelist of EC models.
Capacity is selected separately by the user.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class FlashProtocol:
    name: str
    erase_sector_size: int
    erase_opcode: int
    program_method: str
    flash_id: bytes


def protocol_for(identity, flash_id):
    chip_id, chip_version = identity
    if not 0x8000 <= chip_id <= 0x8FFF or len(flash_id) != 3:
        return None
    v2 = (chip_version & 0x0F) >= 3
    if flash_id == bytes.fromhex("FF FF FE"):
        return FlashProtocol("ITE eFlash 8315", 1024, 0xD7,
                             "aai_v2" if v2 else "aai_legacy", flash_id)
    if flash_id[0] in (0xC8, 0xEF):
        return FlashProtocol("ITE eFlash KGD", 4096, 0x20,
                             "page_program" if v2 else "aai_legacy", flash_id)
    return None
