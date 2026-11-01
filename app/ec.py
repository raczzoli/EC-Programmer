# SPDX-FileCopyrightText: 2026 R89 Repairs and contributors
# SPDX-License-Identifier: GPL-2.0-or-later

"""ITE DBGR flash access, adapted from Chromium EC iteflash.

No model-specific identification is implied by the returned numeric CHIPID.
"""
import hashlib
import time
from pathlib import Path
from .flash_profiles import EFLASH_8315_256K, profile_for

CMD, DATA, BLOCK = 0x5A, 0x35, 0x79
MAX_READ = 1024 * 1024
PAGE_SIZE = 256
SUPPORTED_SIZE = EFLASH_8315_256K.size


class FlashError(RuntimeError):
    pass


class ECProbe:
    def __init__(self, bus, page_mode=False):
        self.bus = bus
        self.page_mode = page_mode

    def reg_read(self, reg):
        self.bus.write(CMD, [reg])
        return self.bus.read(DATA, 1)[0]

    def reg_write(self, reg, value):
        self.bus.write(CMD, [reg])
        self.bus.write(DATA, [value])

    def enter_and_identify(self):
        if self.page_mode:
            return self.bus.enter_dbgr()
        self.bus.wave()
        # Chromium iteflash stops the EC through the DBGR follow-mode registers
        # before reading CHIPVER/CHIPID. These writes do not erase flash.
        for reg, value in ((0x07, 0x7f), (0x06, 0xff),
                           (0x05, 0xfe), (0x04, 0), (0x08, 0),
                           (0x07, 0), (0x06, 0)):
            self.reg_write(reg, value)
        return self.identify()

    def identify(self):
        version = self.reg_read(0x02)
        high = self.reg_read(0x00)
        low = self.reg_read(0x01)
        return (high << 8) | low, version

    def _follow_read(self, address):
        for reg, value in ((0x07, 0x7f), (0x06, 0xff), (0x05, 0xfe),
                           (0x04, 0), (0x08, 0), (0x05, 0xfd),
                           (0x08, 0x0b), (0x08, (address >> 16) & 255),
                           (0x08, (address >> 8) & 255), (0x08, address & 255),
                           (0x08, 0)):
            self.reg_write(reg, value)
        self.bus.write(CMD, [0x09])

    def _follow_mode(self):
        for reg, value in ((0x07, 0x7f), (0x06, 0xff), (0x05, 0xfe),
                           (0x04, 0), (0x08, 0)):
            self.reg_write(reg, value)

    def _spi_command(self, opcode):
        for reg, value in ((0x05, 0xfe), (0x08, 0), (0x05, 0xfd),
                           (0x08, opcode)):
            self.reg_write(reg, value)

    def _poll_status(self, mask, expected, description, timeout=5):
        self._spi_command(0x05)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            status = self.bus.read(DATA, 1)[0]
            if status & mask == expected:
                return
            time.sleep(0.002)
        raise FlashError(f"{description}: flash status timeout")

    def flash_id(self):
        """Read-only 0x9F probe; identifies the flash command set, not capacity."""
        self._follow_mode()
        self._spi_command(0x9f)
        return self.bus.read(BLOCK, 3)

    def supported_geometry(self, identity):
        """Resolve a write profile from hardware IDs, including blank flash."""
        flash_id = self.flash_id()
        profile = profile_for(identity, flash_id)
        if profile is None:
            raise FlashError(
                f"No verified flash profile for CHIPID 0x{identity[0]:04X}, "
                f"CHIPVER 0x{identity[1]:02X}, flash ID {flash_id.hex().upper()}"
            )
        return profile.size

    def _write_enable(self):
        self._spi_command(0x06)
        self._poll_status(3, 2, "write enable")

    def erase_flash(self, size, progress=lambda done, total: None):
        if size != SUPPORTED_SIZE:
            raise FlashError("Unsupported erase size")
        self._follow_mode()
        refreshed = time.monotonic()
        try:
            for address in range(0, size, 1024):
                if time.monotonic() - refreshed > 2:
                    self.bus.read_page(0)
                    self._follow_mode()
                    refreshed = time.monotonic()
                self._write_enable()
                self._spi_command(0xd7)  # 1 KiB sector erase for eFlash 8315
                page = address // PAGE_SIZE
                for value in ((page >> 8) & 255, page & 255, 0):
                    self.reg_write(0x08, value)
                self._poll_status(1, 0, f"erase at 0x{address:06X}", timeout=10)
                self._spi_command(0x04)
                progress(address + 1024, size)
        except Exception:
            try:
                self._spi_command(0x04)
            except Exception:
                pass
            raise

    def write_flash(self, data, progress=lambda done, total: None):
        """Legacy AAI blocks for CHIPVER revisions below 0x03."""
        if len(data) != SUPPORTED_SIZE:
            raise FlashError("Image size does not match the supported flash geometry")
        if (hasattr(self.bus, "fast_aai256_available") and
                self.bus.fast_aai256_available()):
            for address in range(0, len(data), 256):
                block = data[address:address + 256]
                if block != b"\xff" * 256:
                    self.bus.program256(address, block)
                progress(address + 256, len(data))
            return
        if (hasattr(self.bus, "fast_aai_available") and
                self.bus.fast_aai_available()):
            for address in range(0, len(data), 64):
                block = data[address:address + 64]
                if block != b"\xff" * 64:
                    self.bus.program64(address, block)
                progress(address + 64, len(data))
            return
        self._follow_mode()
        refreshed = time.monotonic()
        quick_active = False
        try:
            for address in range(0, len(data), 64):
                if time.monotonic() - refreshed > 2:
                    self.bus.read_page(0)
                    self._follow_mode()
                    refreshed = time.monotonic()
                block = data[address:address + 64]
                if block == b"\xff" * len(block):
                    progress(address + len(block), len(data))
                    continue
                self._write_enable()
                self._spi_command(0xad)
                for value in ((address >> 16) & 255, (address >> 8) & 255,
                              address & 255):
                    self.bus.write(DATA, [value])
                self._poll_status(1, 0, f"AAI start at 0x{address:06X}")
                self.reg_write(0x10, 0x20)
                quick_active = True
                self.bus.write(BLOCK, block)
                self.bus.write(DATA, [0xff])
                self.reg_write(0x10, 0)
                quick_active = False
                self._spi_command(0x04)
                self._poll_status(1, 0, f"AAI finish at 0x{address:06X}")
                progress(address + len(block), len(data))
        except Exception:
            if quick_active:
                try:
                    self.bus.write(DATA, [0xff])
                except Exception:
                    pass
            try:
                self.reg_write(0x10, 0)
                self._spi_command(0x04)
            except Exception:
                pass
            raise

    def verify_flash(self, expected, progress=lambda done, total: None):
        if len(expected) != SUPPORTED_SIZE:
            raise FlashError("Invalid verify length")
        for address in range(0, len(expected), PAGE_SIZE):
            actual = self.bus.read_page(address)
            wanted = expected[address:address + PAGE_SIZE]
            if actual != wanted:
                offset = next(i for i, (a, b) in enumerate(zip(actual, wanted))
                              if a != b)
                raise FlashError(f"Verification failed at 0x{address + offset:06X}")
            progress(address + PAGE_SIZE, len(expected))

    def read_flash(self, size, progress=lambda done, total: None):
        if size < 256 or size > MAX_READ or size % 256:
            raise ValueError("Size must be a multiple of 256 bytes, up to 1 MiB")
        if self.page_mode:
            if size > 256 * 1024:
                raise ValueError("Current page reader is limited to 256 KiB")
            result = bytearray()
            for address in range(0, size, 256):
                result.extend(self.bus.read_page(address))
                progress(len(result), size)
            return bytes(result)
        result = bytearray()
        self._follow_read(0)
        try:
            while len(result) < size:
                address = len(result)
                if address and address % 0x40000 == 0:
                    self._follow_read(address)
                chunk = min(64, size - address)
                result.extend(self.bus.read(BLOCK, chunk))
                progress(len(result), size)
        finally:
            # Exit SPI follow mode as in current Chromium EC iteflash.cc.
            self.reg_write(0x07, 0)
            self.reg_write(0x06, 0)
        return bytes(result)


def save_new(path, data):
    """Exclusive creation: no existing backup is ever overwritten."""
    with open(path, "xb") as f:
        f.write(data)
    return hashlib.sha256(data).hexdigest()


def compare_reads(first, second):
    h1, h2 = hashlib.sha256(first).hexdigest(), hashlib.sha256(second).hexdigest()
    mismatch = next((i for i, (a, b) in enumerate(zip(first, second)) if a != b), None)
    if mismatch is None and len(first) != len(second):
        mismatch = min(len(first), len(second))
    return h1, h2, mismatch


def validate_image(path, size):
    data = Path(path).read_bytes()
    if len(data) != size:
        raise ValueError(f"Image has {len(data)} bytes; selected flash size is {size} bytes")
    return hashlib.sha256(data).hexdigest()
