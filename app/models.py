# SPDX-FileCopyrightText: 2026 R89 Repairs and contributors
# SPDX-License-Identifier: GPL-2.0-or-later

"""Target family choices and their transport backends."""
from dataclasses import dataclass
from .geometry import FLASH_SIZES
from .ene_families import ene_family
from .ene_models import ENE_MODELS


@dataclass(frozen=True)
class Family:
    name: str
    read_protocol: bool = False
    transport: str = "ite"

    @property
    def flash_sizes(self):
        return ene_family(self.name).sizes if self.transport == "ene_edi" else FLASH_SIZES

    @property
    def fixed_flash_size(self):
        sizes = self.flash_sizes
        return sizes[0] if len(sizes) == 1 else None


FAMILIES = (
    Family("IT51xx"),
    Family("IT55xx"),
    Family("IT8xxx", True),
)

FAMILIES_BY_MANUFACTURER = {
    "ITE": FAMILIES,
    "ENE": tuple(Family(group.name, True, "ene_edi") for group in ENE_MODELS),
}
