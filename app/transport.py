"""USB CDC transport for the bundled Pico firmware."""
import re
import serial
import time
from serial.tools import list_ports


class TransportError(RuntimeError):
    pass


def ports():
    found = list(list_ports.comports())
    found.sort(key=lambda p: (p.vid != 0x2E8A, p.vid is None, p.device))
    return [(p.device, p.description) for p in found]


class PicoTransport:
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
        self.close()

    def __init__(self, port, timeout=2):
        self.port = serial.Serial(port, 115200, timeout=timeout, write_timeout=timeout)
        self._fast_aai = None
        self._fast_aai256 = False
        try:
            self.port.reset_input_buffer()
            answer = self.command("HELLO")
            if answer not in ("OK PICO_ITE_EC_PROGRAMMER 2",
                              "OK PICO_EC_PROBE 1 PROBE_ONLY"):
                raise TransportError(f"Incompatible firmware: {answer}")
        except Exception:
            self.port.close()
            raise

    def close(self):
        if self.port.is_open:
            try:
                self.command("RELEASE")
            finally:
                self.port.close()

    def command(self, text):
        try:
            self.port.write((text + "\n").encode("ascii"))
            response = self.port.readline()
        except (serial.SerialException, OSError) as exc:
            raise TransportError(f"USB disconnected or serial error: {exc}") from exc
        if not response:
            raise TransportError("Timeout USB CDC")
        answer = response.decode("ascii", errors="replace").strip()
        if answer.startswith("ERR "):
            raise TransportError(answer)
        return answer

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
        answer = self.command(f"READPAGE {address:06X}")
        match = re.fullmatch(r"PAGE ([0-9A-F]{6}) ([0-9A-F]{512})", answer)
        if not match or int(match[1], 16) != address:
            raise TransportError(f"Invalid flash page response at 0x{address:06X}: {answer[:80]}")
        return bytes.fromhex(match[2])

    def fast_aai_available(self):
        if self._fast_aai is None:
            try:
                answer = self.command("CAPS")
            except TransportError as exc:
                if str(exc) != "ERR COMMAND":
                    raise
                self._fast_aai = False
            else:
                self._fast_aai = "AAI64" in answer.split()[1:]
                self._fast_aai256 = "AAI256" in answer.split()[1:]
        return self._fast_aai

    def fast_aai256_available(self):
        self.fast_aai_available()
        return self._fast_aai256

    def program256(self, address, data):
        if address < 0 or address > 0x3ff00 or address & 255 or len(data) != 256:
            raise ValueError("AAI256 requires an aligned 256-byte block within 256 KiB")
        previous_timeout = self.port.timeout
        self.port.timeout = max(previous_timeout, 12)
        try:
            answer = self.command(f"AAI256 {address:06X} {bytes(data).hex().upper()}")
        finally:
            self.port.timeout = previous_timeout
        if answer != f"AAI256 {address:06X} OK":
            raise TransportError(f"Unexpected AAI256 response: {answer}")

    def program64(self, address, data):
        if address < 0 or address > 0x3ffc0 or address & 63 or len(data) != 64:
            raise ValueError("AAI64 requires an aligned 64-byte block within 256 KiB")
        previous_timeout = self.port.timeout
        self.port.timeout = max(previous_timeout, 12)
        try:
            answer = self.command(f"AAI64 {address:06X} {bytes(data).hex().upper()}")
        finally:
            self.port.timeout = previous_timeout
        if answer != f"AAI64 {address:06X} OK":
            raise TransportError(f"Unexpected AAI64 response: {answer}")

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
