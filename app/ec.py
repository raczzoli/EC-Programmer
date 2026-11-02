# SPDX-FileCopyrightText: 2026 R89 Repairs and contributors
# SPDX-License-Identifier: GPL-2.0-or-later

"""ITE DBGR flash access, adapted from Chromium EC iteflash.

No model-specific identification is implied by the returned numeric CHIPID.
"""
import hashlib
import time
from pathlib import Path
from .flash_protocols import protocol_for
from .transport import TransportError
from .geometry import PAGE_SIZE, FLASH_SIZES, MAX_FLASH_SIZE

CMD, DATA, BLOCK = 0x5A, 0x35, 0x79
MAX_READ = 1024 * 1024


class FlashError(RuntimeError):
    pass


class ECProbe:
    def __init__(self, bus, page_mode=False):
        self.bus = bus
        self.page_mode = page_mode

    def _supports(self, capability):
        return hasattr(self.bus, "supports") and self.bus.supports(capability)

    def reg_read(self, reg):
        if self._supports("REGIO"):
            return self.bus.reg_read(reg)
        self.bus.write(CMD, [reg])
        return self.bus.read(DATA, 1)[0]

    def reg_write(self, reg, value):
        if self._supports("REGIO"):
            self.bus.reg_write(reg, value)
            return
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
        if self.page_mode and self._supports("SESSION"):
            return self.bus.session()
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
        atomic = self._supports("SPISTATUS")
        if not atomic:
            self._spi_command(0x05)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            status = self.bus.spi_status() if atomic else self.bus.read(DATA, 1)[0]
            if status & mask == expected:
                return
            time.sleep(0.002)
        raise FlashError(f"{description}: flash status timeout")

    def flash_id(self):
        """Read-only 0x9F probe; identifies the flash command set, not capacity."""
        if self._supports("FLASHID"):
            return self.bus.flash_id(BLOCK)
        self._follow_mode()
        self._spi_command(0x9f)
        return self.bus.read(BLOCK, 3)

    def flash_protocol(self, identity):
        """Classify the command set from EC identity and flash ID."""
        try:
            flash_id = self.flash_id()
        except TransportError as exc:
            if not any(code in str(exc) for code in ("ADDRESS_NACK", "DATA_NACK")):
                raise
            flash_id = b""
        protocol = protocol_for(identity, flash_id)
        if protocol is None:
            # Chromium iteflash reads 0x9F through DATA (0x35). Preserve the
            # existing BLOCK probe for already working targets, then try DATA.
            if self._supports("FLASHID"):
                flash_id = self.bus.flash_id(DATA)
            else:
                self._follow_mode()
                self._spi_command(0x9f)
                flash_id = self.bus.read(DATA, 3)
            protocol = protocol_for(identity, flash_id)
        if protocol is None:
            raise FlashError(
                f"Unsupported flash protocol for CHIPID 0x{identity[0]:04X}, "
                f"CHIPVER 0x{identity[1]:02X}, flash ID {flash_id.hex().upper()}"
            )
        return protocol

    def _write_enable(self):
        self._spi_command(0x06)
        self._poll_status(3, 2, "write enable")

    def erase_flash(self, size, protocol, progress=lambda done, total: None):
        if size not in FLASH_SIZES or size % protocol.erase_sector_size:
            raise FlashError("Unsupported erase size")
        if self._supports("ERASESECTOR"):
            for address in range(0, size, protocol.erase_sector_size):
                self.bus.erase_sector(address, protocol.erase_opcode)
                progress(address + protocol.erase_sector_size, size)
            return
        self._follow_mode()
        refreshed = time.monotonic()
        try:
            for address in range(0, size, protocol.erase_sector_size):
                if time.monotonic() - refreshed > 2:
                    self.bus.read_page(0)
                    self._follow_mode()
                    refreshed = time.monotonic()
                self._write_enable()
                self._spi_command(protocol.erase_opcode)
                page = address // PAGE_SIZE
                for value in ((page >> 8) & 255, page & 255, 0):
                    self.reg_write(0x08, value)
                self._poll_status(1, 0, f"erase at 0x{address:06X}", timeout=10)
                self._spi_command(0x04)
                progress(address + protocol.erase_sector_size, size)
        except Exception:
            try:
                self._spi_command(0x04)
            except Exception:
                pass
            raise

    def write_flash(self, data, protocol, progress=lambda done, total: None):
        """Program selected capacity with the identified flash command set."""
        if len(data) not in FLASH_SIZES:
            raise FlashError("Image size is not a selectable flash capacity")
        if protocol.program_method == "page_program":
            self._write_pages(data, progress)
            return
        if protocol.program_method == "aai_v2":
            self._write_aai_v2(data, progress)
            return
        if protocol.program_method != "aai_legacy":
            raise FlashError("Unsupported programming method")
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

    def _write_aai_v2(self, data, progress):
        """DX AAI sequence: first word on DATA, remainder in quick block mode."""
        if (hasattr(self.bus, "fast_aai_v2_256_available") and
                self.bus.fast_aai_v2_256_available()):
            for address in range(0, len(data), 256):
                block = data[address:address + 256]
                if block != b"\xff" * 256:
                    self.bus.program_v2_256(address, block)
                progress(address + 256, len(data))
            return
        if (hasattr(self.bus, "fast_aai_v2_available") and
                self.bus.fast_aai_v2_available()):
            for address in range(0, len(data), 64):
                block = data[address:address + 64]
                if block != b"\xff" * 64:
                    self.bus.program_v2_64(address, block)
                progress(address + 64, len(data))
            return
        self._follow_mode()
        try:
            for address in range(0, len(data), 64):
                block = data[address:address + 64]
                if block != b"\xff" * 64:
                    self._write_enable()
                    self._spi_command(0xAD)
                    for value in ((address >> 16) & 255, (address >> 8) & 255,
                                  address & 255, block[0], block[1]):
                        self.bus.write(DATA, [value])
                    self._poll_status(1, 0, f"AAI start at 0x{address:06X}")
                    self.reg_write(0x10, 0x20)
                    try:
                        self.bus.write(BLOCK, block[2:])
                        self.bus.write(DATA, [0xFF])
                    finally:
                        self.reg_write(0x10, 0)
                    self._spi_command(0x04)
                    self._poll_status(1, 0, f"AAI finish at 0x{address:06X}")
                progress(address + 64, len(data))
        finally:
            self._spi_command(0x04)

    def _write_pages(self, data, progress):
        """KGD SPI page program; each 64-byte transaction stays within a page."""
        if (hasattr(self.bus, "fast_page_available") and
                self.bus.fast_page_available()):
            for address in range(0, len(data), 64):
                block = data[address:address + 64]
                if block != b"\xff" * 64:
                    self.bus.program_v2_64(address, block, page_program=True)
                progress(address + 64, len(data))
            return
        self._follow_mode()
        try:
            for address in range(0, len(data), 64):
                block = data[address:address + 64]
                if block != b"\xff" * 64:
                    self._write_enable()
                    self._spi_command(0x02)
                    for value in ((address >> 16) & 255, (address >> 8) & 255,
                                  address & 255):
                        self.bus.write(DATA, [value])
                    self.bus.write(BLOCK, block)
                    self._poll_status(1, 0, f"page program at 0x{address:06X}")
                    self._spi_command(0x04)
                progress(address + 64, len(data))
        finally:
            self._spi_command(0x04)

    def verify_flash(self, expected, progress=lambda done, total: None):
        if len(expected) not in FLASH_SIZES:
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
            if size > MAX_FLASH_SIZE:
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
