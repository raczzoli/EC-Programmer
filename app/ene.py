# SPDX-FileCopyrightText: 2026 R89 Repairs and contributors
# SPDX-License-Identifier: GPL-2.0-or-later

"""Shared ENE EDI eFlash access through the bundled Pico SPI0 firmware.

The EDI register/flash sequence follows flashrom's GPL-2.0-or-later edi.c.
Compatibility groups and sources are documented in docs/ENE.md.
"""

import re
from dataclasses import dataclass

from .ec import FlashError
from .transport import TransportError
from .ene_families import PAGE_SIZE, ene_family


@dataclass(frozen=True)
class EneFlashProtocol:
    family: str
    identity: tuple[int, int]
    name: str = "ENE EDI eFlash"
    program_method: str = "ene_page"


class EneEC:
    def __init__(self, bus, family="KB9052 (B/D)"):
        self.bus = bus
        self.family = ene_family(family)
        self.identity = None

    def enter_and_identify(self):
        self.identity = None
        caps = self.bus.command("CAPS").split()
        if not caps or caps[0] != "CAPS" or "ENE_EDI_V2" not in caps[1:]:
            raise TransportError("Pico firmware needs ENE_EDI_V2 support; install the matching new UF2")
        answer = self.bus.command(f"ENEOPEN {self.family.command}")
        match = re.fullmatch(r"ENEOPEN HW=([0-9A-F]{2}) EDI=([0-9A-F]{2})", answer)
        if not match:
            raise TransportError(f"Invalid ENE response: {answer}")
        identity = (int(match[1], 16), int(match[2], 16))
        if not self.family.accepts_identity(identity):
            raise FlashError(f"ENE HW/EDI {identity[0]:02X}/{identity[1]:02X} does not match {self.family.name}")
        self.identity = identity
        return identity

    def flash_protocol(self, identity):
        if self.identity is None or identity != self.identity:
            raise FlashError("ENE identity changed")
        return EneFlashProtocol(self.family.name, identity)

    def _check_size(self, size):
        if self.identity is None:
            raise FlashError("Connect to the ENE before accessing flash")
        if size not in self.family.sizes:
            allowed = "/".join(str(value // 1024) for value in self.family.sizes)
            raise FlashError(f"{self.family.name} supports selected ranges of {allowed} KiB")

    def _read_page(self, address):
        answer = self.bus.command(f"ENEREADPAGE {address:05X}")
        match = re.fullmatch(r"ENEPAGE ([0-9A-F]{5}) ([0-9A-F]{256})", answer)
        if not match or int(match[1], 16) != address:
            raise TransportError(f"Invalid ENE page response at 0x{address:05X}: {answer[:80]}")
        return bytes.fromhex(match[2])

    def read_flash(self, size, progress=lambda done, total: None):
        self._check_size(size)
        result = bytearray()
        for address in range(0, size, PAGE_SIZE):
            result.extend(self._read_page(address))
            progress(address + PAGE_SIZE, size)
        return bytes(result)

    def erase_flash(self, size, protocol, progress=lambda done, total: None):
        self._check_size(size)
        self._check_protocol(protocol)
        for address in range(0, size, PAGE_SIZE):
            answer = self.bus.command(f"ENEERASEPAGE {address:05X}")
            if answer != f"ENEERASEPAGE {address:05X} OK":
                raise TransportError(f"Invalid ENE erase response at 0x{address:05X}: {answer}")
            progress(address + PAGE_SIZE, size)

    def _check_protocol(self, protocol):
        if (not isinstance(protocol, EneFlashProtocol) or self.identity is None or
                protocol != self.flash_protocol(self.identity)):
            raise FlashError("Invalid ENE flash protocol")

    def write_flash(self, data, protocol, progress=lambda done, total: None):
        self._check_size(len(data))
        self._check_protocol(protocol)
        for address in range(0, len(data), PAGE_SIZE):
            page = data[address:address + PAGE_SIZE]
            # ENE EDI erase produces zero-filled pages.
            if any(page):
                answer = self.bus.command(f"ENEWRITEPAGE {address:05X} {page.hex().upper()}")
                if answer != f"ENEWRITEPAGE {address:05X} OK":
                    raise TransportError(f"Invalid ENE write response at 0x{address:05X}: {answer}")
            progress(address + PAGE_SIZE, len(data))

    def verify_flash(self, expected, progress=lambda done, total: None):
        self._check_size(len(expected))
        for address in range(0, len(expected), PAGE_SIZE):
            actual = self._read_page(address)
            wanted = expected[address:address + PAGE_SIZE]
            if actual != wanted:
                offset = next(i for i, (a, b) in enumerate(zip(actual, wanted)) if a != b)
                raise FlashError(f"ENE verification failed at 0x{address + offset:05X}")
            progress(address + PAGE_SIZE, len(expected))
