# SPDX-FileCopyrightText: 2026 R89 Repairs and contributors
# SPDX-License-Identifier: GPL-2.0-or-later

"""ITE family choices; model-specific experiments stay outside the GUI."""
from dataclasses import dataclass


@dataclass(frozen=True)
class Family:
    name: str
    read_protocol: bool = False


FAMILIES = (
    Family("IT51xx"),
    Family("IT55xx"),
    Family("IT8xxx", True),
)

FAMILIES_BY_MANUFACTURER = {"ITE": FAMILIES}
