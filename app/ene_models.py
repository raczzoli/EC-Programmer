# SPDX-FileCopyrightText: 2026 R89 Repairs and contributors
# SPDX-License-Identifier: GPL-2.0-or-later

"""Documented physical packages. Protocol engines remain shared by family.

Sources and package/revision scope: docs/ENE_PINOUTS.md.
Numbers refer to the EC itself, never to a keyboard connector.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class EneModel:
    name: str
    family: str
    identities: frozenset[tuple[int, int]]
    source: str
    package: str = "LQFP-128"
    # Ordered pairs: Pico GPIO, physical EC pin.
    pins: tuple[tuple[int, int], ...] = ((4, 62), (5, 59), (6, 60), (7, 61))
    strap: int = 42

    @property
    def wiring(self):
        signals = "  |  ".join(f"Pico GP{gpio} = EC pin {pin}" for gpio, pin in self.pins)
        return (f"{self.name} ({self.package}): {signals}\n"
                f"Pico GND = Board GND  |  EC pin {self.strap} (KSO3) = Board GND")


ENE_MODELS = (
    EneModel("KB9012QF", "KB901x", frozenset({(0xC3, 0x04)}),
             "ENE KB9012 datasheet, section 2.1 (LQFP-128)"),
    EneModel("KB9022Q", "KB902x", frozenset({(0xB1, 0x07)}),
             "Compal LA-E892P rev 1A, sheet 37, UB1"),
    EneModel("KB9028Q", "KB902x", frozenset({(0xC0, 0x07)}),
             "MSI MS-16K2/17B1 rev 0B, EC U25, KB9028Q-C-RH"),
    EneModel("KB902FQ C", "KB902FQ", frozenset(),
             "ASUS X541NA rev 2.1 BoardView, U3001, KB902FQ C LQFP128"),
    EneModel("KB9052QD", "KB9052 (B/D)", frozenset({(0xD0, 0x0B)}),
             "Compal FH5LI LA-J801P rev 1.0, EC_ENE KB9052Q, KB9052Q-D_LQFP128"),
)


def ene_model(name):
    return next((model for model in ENE_MODELS if model.name == name), None)
