# SPDX-FileCopyrightText: 2026 R89 Repairs and contributors
# SPDX-License-Identifier: GPL-2.0-or-later

"""USB CDC transport for the bundled Pico firmware."""
import re
import serial
import time
import secrets
from serial.tools import list_ports
from .geometry import MAX_FLASH_SIZE, PAGE_SIZE


class TransportError(RuntimeError):
    pass


def ports():
    found = list(list_ports.comports())
    found.sort(key=lambda p: (p.vid != 0x2E8A, p.vid is None, p.device))
    return [(p.device, p.description) for p in found]


class PicoTransport:
    COMMAND_TIMEOUTS = {
        "AAI64": 25, "AAI256": 25, "AAIV2_64": 25,
        "AAIV2_256": 25, "PAGE64": 25, "ERASESECTOR": 25,
        "ENTERDBGR": 8, "WAVESWEEP": 8, "WAVEPOWER": 50,
        "ENEOPEN": 15,
    }
    @staticmethod
    def wait_power_cycle(port, pins, status=lambda message: None):
        """Arm the Pico before target power is removed and restored."""
        with PicoTransport(port, timeout=5) as bus:
            bus.pins(*pins)
        with serial.Serial(port, 115200, timeout=1, write_timeout=2) as link:
            time.sleep(0.25)
            link.reset_input_buffer()
            link.write(b"WAVEPOWER\n")
            deadline = time.monotonic() + 45
            while time.monotonic() < deadline:
                raw = link.readline()
                if not raw:
                    continue
                answer = raw.decode("ascii", errors="replace").strip()
                if answer == "READY WAVEPOWER WAIT_POWER_OFF":
                    status("Pico is armed: unplug laptop power for 5 seconds, then reconnect it.")
                elif answer == "POWER_OFF_DETECTED WAIT_POWER_ON":
                    status("Power off detected: reconnect laptop power now.")
                elif answer.startswith("WAVEPOWER "):
                    if not re.fullmatch(r"WAVEPOWER \d+ ADDRESS_ACK", answer):
                        status(f"Power-on waveform did not ACK ({answer}); trying direct entry now.")
                        return False
                    status("Power cycle captured; entering EC debug mode.")
                    return True
                elif answer.startswith("ERR WAVEPOWER_"):
                    raise TransportError(answer)
            raise TransportError("Timed out waiting for the laptop power cycle")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        try:
            self.close()
        except TransportError:
            if exc_type is None:
                raise

    def __init__(self, port, timeout=2):
        self.port = serial.Serial(port, 115200, timeout=timeout, write_timeout=timeout)
        self._fast_aai = None
        self._fast_aai256 = False
        self._fast_aai_v2 = False
        self._fast_aai_v2_256 = False
        self._fast_page = False
        self._caps = None
        self._tagged = False
        self._sequence = secrets.randbits(32)
        self._synchronized = True
        try:
            self.port.reset_input_buffer()
            # HELLO is a barrier after any command left running by a prior
            # connection. Ignore its old replies until our handshake arrives.
            self.port.write(b"HELLO\n")
            deadline = time.monotonic() + timeout
            while True:
                response = self.port.readline()
                if response.endswith(b"\n") and response.rstrip(b"\r\n") in (
                        b"OK PICO_ITE_EC_PROGRAMMER 2", b"OK PICO_EC_PROBE 1 PROBE_ONLY"):
                    break
                if not response or time.monotonic() >= deadline:
                    raise TransportError("Pico handshake failed; reconnect after the pending command finishes")
        except Exception:
            self.port.close()
            raise

    def close(self):
        if self.port.is_open:
            try:
                # A timed-out flash command may still be executing. Do not
                # queue another target command behind it or consume its reply.
                if self._synchronized and self.command("RELEASE") != "OK":
                    raise TransportError("Invalid RELEASE acknowledgement")
            finally:
                self.port.close()

    def command(self, text):
        if not self._synchronized:
            raise TransportError("USB session is out of sync; reconnect before another operation")
        if not text.strip() or "\n" in text or "\r" in text:
            raise ValueError("Expected one USB command")
        self._sequence = (self._sequence + 1) & 0xFFFFFFFF
        tag = f"@{self._sequence:08X} " if self._tagged else ""
        previous_timeout = self.port.timeout
        timeout = max(previous_timeout or 0, self.COMMAND_TIMEOUTS.get(text.split()[0], 5))
        deadline = time.monotonic() + timeout
        try:
            self.port.write((tag + text + "\n").encode("ascii"))
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TransportError("Timeout USB CDC; command outcome is unknown")
                self.port.timeout = remaining
                response = self.port.readline()
                if not response or not response.endswith(b"\n"):
                    raise TransportError("Timeout USB CDC or incomplete response; reconnect")
                answer = response.decode("ascii").strip()
                if tag:
                    if not answer.startswith(tag):
                        continue
                    answer = answer[len(tag):]
                break
        except (serial.SerialException, OSError) as exc:
            self._synchronized = False
            raise TransportError(f"USB disconnected or serial error: {exc}") from exc
        except (TransportError, UnicodeError) as exc:
            self._synchronized = False
            raise TransportError(str(exc)) from exc
        finally:
            self.port.timeout = previous_timeout
        if answer.startswith("ERR "):
            raise TransportError(answer)
        return answer

    def capabilities(self):
        if self._caps is None:
            try:
                answer = self.command("CAPS")
            except TransportError as exc:
                if str(exc) != "ERR COMMAND":
                    raise
                self._caps = frozenset()
            else:
                if not answer.startswith("CAPS "):
                    self._synchronized = False
                    raise TransportError(f"Invalid capabilities response: {answer}")
                self._caps = frozenset(answer.split()[1:])
                self._tagged = "TAGGED" in self._caps
        return self._caps

    def supports(self, capability):
        return capability in self.capabilities()

    def firmware_info(self):
        return self.command("INFO") if self.supports("INFO") else "INFO legacy firmware"

    def reg_read(self, reg):
        answer = self.command(f"REGREAD {reg:02X}")
        match = re.fullmatch(r"REG ([0-9A-F]{2}) ([0-9A-F]{2})", answer)
        if not match or int(match[1],16) != reg:
            raise TransportError(f"Invalid register response: {answer}")
        return int(match[2],16)

    def reg_write(self, reg, value):
        if self.command(f"REGWRITE {reg:02X} {value:02X}") != "OK":
            raise TransportError("Register write not acknowledged")

    def spi_status(self):
        answer = self.command("SPISTATUS")
        if not re.fullmatch(r"STATUS [0-9A-F]{2}", answer):
            raise TransportError(f"Invalid flash status: {answer}")
        return int(answer[7:],16)

    def flash_id(self, port):
        answer = self.command(f"FLASHID {port:02X}")
        if not re.fullmatch(r"FLASHID [0-9A-F]{6}", answer):
            raise TransportError(f"Invalid flash ID response: {answer}")
        return bytes.fromhex(answer[8:])

    def session(self):
        answer = self.command("SESSION")
        match = re.fullmatch(r"SESSION CHIPID=([0-9A-F]{4}) CHIPVER=([0-9A-F]{2})", answer)
        if not match:
            raise TransportError(f"Invalid session response: {answer}")
        return int(match[1],16), int(match[2],16)

    def erase_sector(self, address, opcode):
        if self.command(f"ERASESECTOR {address:06X} {opcode:02X}") != f"ERASESECTOR {address:06X} OK":
            raise TransportError("Sector erase not acknowledged")

    def pins(self, sda, scl):
        if self.command(f"PINS {sda} {scl}") != "OK":
            raise TransportError("Pin configuration failed")

    def wave(self):
        answer = self.command("WAVESWEEP")
        if not answer.startswith("SWEEP ") or not re.search(r"\b\d+:ACK\b", answer):
            raise TransportError(f"DBGR entry sequence failed: {answer}")

    def enter_dbgr(self):
        answer = self.command("ENTERDBGR")
        match = re.fullmatch(
            r"ENTERDBGR RATE=\d+ CHIPID=([0-9A-F]{4}) CHIPVER=([0-9A-F]{2}) WDT=[0-9A-F]{2}",
            answer,
        )
        if not match:
            raise TransportError(f"DBGR identification failed: {answer}")
        return int(match[1], 16), int(match[2], 16)

    def read_page(self, address):
        if address < 0 or address > MAX_FLASH_SIZE - PAGE_SIZE or address % PAGE_SIZE:
            raise ValueError("READPAGE requires an aligned page within the supported flash range")
        answer = self.command(f"READPAGE {address:06X}")
        match = re.fullmatch(r"PAGE ([0-9A-F]{6}) ([0-9A-F]{512})", answer)
        if not match or int(match[1], 16) != address:
            raise TransportError(f"Invalid flash page response at 0x{address:06X}: {answer[:80]}")
        return bytes.fromhex(match[2])

    def fast_aai_available(self):
        if self._fast_aai is None:
            caps = self.capabilities()
            self._fast_aai = "AAI64" in caps
            self._fast_aai256 = "AAI256" in caps
            self._fast_aai_v2 = "AAIV2_64" in caps
            self._fast_aai_v2_256 = "AAIV2_256" in caps
            self._fast_page = "PAGE64" in caps
        return self._fast_aai

    def fast_aai256_available(self):
        self.fast_aai_available()
        return self._fast_aai256

    def fast_aai_v2_available(self):
        self.fast_aai_available()
        return self._fast_aai_v2

    def fast_aai_v2_256_available(self):
        self.fast_aai_available()
        return self._fast_aai_v2_256

    def fast_page_available(self):
        self.fast_aai_available()
        return self._fast_page

    def program_v2_64(self, address, data, page_program=False):
        name = "PAGE64" if page_program else "AAIV2_64"
        self._program_block(name, address, data, 64)

    def program_v2_256(self, address, data):
        self._program_block("AAIV2_256", address, data, 256)

    def program256(self, address, data):
        self._program_block("AAI256", address, data, 256)

    def program64(self, address, data):
        self._program_block("AAI64", address, data, 64)

    def _program_block(self, name, address, data, count):
        if (address < 0 or address > MAX_FLASH_SIZE - count or
                address % count or len(data) != count):
            raise ValueError(f"{name} requires an aligned {count}-byte block within 256 KiB")
        answer = self.command(f"{name} {address:06X} {bytes(data).hex().upper()}")
        if answer != f"{name} {address:06X} OK":
            raise TransportError(f"Unexpected {name} response: {answer}")

    def write(self, address, data):
        if not data or len(data) > 64:
            raise ValueError("I2C transfer must contain 1–64 bytes")
        if self.command(f"WRITE {address:02X} {bytes(data).hex().upper()}") != "OK":
            raise TransportError("I2C register write failed")

    def read(self, address, count):
        if not 1 <= count <= 64:
            raise ValueError("I2C read must request 1–64 bytes")
        response = self.command(f"READ {address:02X} {count}")
        if not re.fullmatch(r"DATA [0-9A-F]+", response):
            raise TransportError(f"Invalid USB response: {response}")
        data = bytes.fromhex(response[5:])
        if len(data) != count:
            raise TransportError("I2C response length does not match the request")
        return data
