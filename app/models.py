# SPDX-FileCopyrightText: 2026 R89 Repairs and contributors
# SPDX-License-Identifier: GPL-2.0-or-later

"""Target family choices and their transport backends."""
from dataclasses import dataclass


@dataclass(frozen=True)
class Family:
    name: str
    read_protocol: bool = False
    transport: str = "ite"


FAMILIES = (
    Family("IT51xx"),
    Family("IT55xx"),
    Family("IT8xxx", True),
)

FAMILIES_BY_MANUFACTURER = {
    "ITE": FAMILIES,
    "ENE": (Family("KB90xx EDI", True, "ene_edi"),),
}
