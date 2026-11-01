# SPDX-FileCopyrightText: 2026 R89 Repairs and contributors
# SPDX-License-Identifier: GPL-2.0-or-later

"""Flash geometries supported by the current ITE DBGR implementation.

An EC family selection enables discovery. Destructive operations require a
separately identified flash profile; numeric IDs are protocol data, not a
claim about a package marking or a particular computer.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class FlashProfile:
    name: str
    chip_id: int
    chip_version: int
    flash_id: bytes
    size: int
    erase_sector_size: int


EFLASH_8315_256K = FlashProfile(
    name="ITE eFlash 8315, 256 KiB",
    chip_id=0x8227,
    chip_version=0x02,
    flash_id=bytes.fromhex("FF FF FE"),
    size=256 * 1024,
    erase_sector_size=1024,
)

FLASH_PROFILES = (EFLASH_8315_256K,)


def profile_for(identity, flash_id):
    return next(
        (profile for profile in FLASH_PROFILES
         if identity == (profile.chip_id, profile.chip_version)
         and flash_id == profile.flash_id),
        None,
    )
