# SPDX-FileCopyrightText: 2026 R89 Repairs and contributors
# SPDX-License-Identifier: GPL-2.0-or-later

"""Documented EDI compatibility groups, not a list of PCB firmware images.

See docs/ENE.md for sources, revision differences and validation limits.
Size comes from the documented interface group, not a capacity measurement.
"""
from dataclasses import dataclass, replace
from .ene_models import ene_model

PAGE_SIZE = 128


@dataclass(frozen=True)
class EneFamily:
    name: str
    command: str
    identities: frozenset[tuple[int, int]]
    sizes: tuple[int, ...]


ENE_FAMILIES = (
    EneFamily("KB901x", "KB901X", frozenset({(0xC3, 0x04)}), (128 * 1024,)),
    EneFamily("KB902x", "KB902X", frozenset({(0xB1, 0x07), (0xC0, 0x07)}), (128 * 1024,)),
    EneFamily("KB9052 (B/D)", "KB9052", frozenset({(0xB0, 0x0B), (0xD0, 0x0B)}), (128 * 1024,)),
    # F0/07 is the upstream KB9542GF signature. A0/07 is the community
    # KB9542 signature; it uses the legacy entry variant, not F0's WDT value.
    EneFamily("KB9542GF", "KB9542GF", frozenset({(0xF0, 0x07), (0xA0, 0x07)}),
              (160 * 1024,)),
)


def ene_family(name):
    model = ene_model(name)
    if model is not None:
        group = ene_family(model.family)
        return replace(group, name=model.name, identities=model.identities)
    for family in ENE_FAMILIES:
        if family.name == name:
            return family
    raise ValueError(f"Unknown ENE family: {name}")
