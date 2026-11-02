# SPDX-FileCopyrightText: 2026 R89 Repairs and contributors
# SPDX-License-Identifier: GPL-2.0-or-later

"""ENE KB9052 EDI flash access through the bundled Pico SPI0 firmware.

The EDI register/flash sequence follows flashrom's GPL-2.0-or-later edi.c.
The B/D identification pairs are from the KB9052 flashrom extension by
Jack O'Neo; these signatures identify the interface, not the PCB firmware.
"""

import re
from dataclasses import dataclass

from .ec import FlashError
from .transport import TransportError

PAGE_SIZE = 128
FLASH_SIZE = 128 * 1024
SUPPORTED_IDS = {(0xB0, 0x0B), (0xD0, 0x0B)}


@dataclass(frozen=True)
class EneFlashProtocol:
    name: str = "ENE EDI eFlash"
    program_method: str = "ene_page"


class EneEC:
    def __init__(self, bus):
        self.bus = bus

    def enter_and_identify(self):
        caps = self.bus.command("CAPS").split()
        if "ENE_EDI" not in caps[1:]:
            raise TransportError("Pico firmware does not support ENE EDI; install the new UF2")
        answer = self.bus.command("ENEOPEN")
        match = re.fullmatch(r"ENEOPEN HW=([0-9A-F]{2}) EDI=([0-9A-F]{2})", answer)
        if not match:
            raise TransportError(f"Invalid ENE response: {answer}")
        identity = (int(match[1], 16), int(match[2], 16))
        if identity not in SUPPORTED_IDS:
            raise FlashError(f"Unsupported ENE HW/EDI ID: {identity[0]:02X}/{identity[1]:02X}")
        return identity

    def flash_protocol(self, identity):
        if identity not in SUPPORTED_IDS:
            raise FlashError("ENE identity changed")
        return EneFlashProtocol()

    def _check_size(self, size):
        if size != FLASH_SIZE:
            raise FlashError("KB9052 EDI supports only a 128 KiB image")

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

    @staticmethod
    def _check_protocol(protocol):
        if not isinstance(protocol, EneFlashProtocol):
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
