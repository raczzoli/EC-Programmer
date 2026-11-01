# SPDX-FileCopyrightText: 2026 R89 Repairs and contributors
# SPDX-License-Identifier: GPL-2.0-or-later

import unittest
from unittest.mock import patch

from app import transport


class FakeSerialError(Exception): pass


class FakePort:
    def __init__(self, *args, **kwargs):
        self.is_open = True
        self.timeout = kwargs.get("timeout", 2)
        self.written = []
        self.replies = [b"OK PICO_ITE_EC_PROGRAMMER 2\n"]

    def reset_input_buffer(self): pass
    def write(self, data): self.written.append(data)
    def readline(self): return self.replies.pop(0) if self.replies else b""
    def close(self): self.is_open = False
    def __enter__(self): return self
    def __exit__(self, *args): self.close()


class TransportTests(unittest.TestCase):
    def setUp(self):
        self.serial_patch = patch.object(transport.serial, "Serial", FakePort)
        self.serial_patch.start()
        self.addCleanup(self.serial_patch.stop)

    def test_echo_and_read_length(self):
        bus = transport.PicoTransport("COM1")
        self.assertEqual(bus.port.written[0], b"HELLO\n")
        bus.port.replies.append(b"DATA AB12\n")
        self.assertEqual(bus.read(0x35, 2), b"\xAB\x12")
        bus.port.replies.append(b"DATA AB\n")
        with self.assertRaises(transport.TransportError): bus.read(0x35, 2)

    def test_error_and_timeout(self):
        bus = transport.PicoTransport("COM1")
        bus.port.replies.append(b"ERR I2C_ACK_OR_TIMEOUT\n")
        with self.assertRaisesRegex(transport.TransportError, "I2C"):
            bus.write(0x5A, b"\x00")
        with self.assertRaisesRegex(transport.TransportError, "Timeout"):
            bus.command("READ 35 1")

    def test_fast_aai_capability_and_block_response(self):
        bus = transport.PicoTransport("COM1")
        bus.port.replies.append(b"CAPS AAI64\n")
        self.assertTrue(bus.fast_aai_available())
        bus.port.replies.append(b"AAI64 000040 OK\n")
        bus.program64(0x40, b"\x5a" * 64)
        self.assertEqual(bus.port.timeout, 2)
        self.assertTrue(bus.port.written[-1].startswith(b"AAI64 000040 5A5A"))
        with self.assertRaises(ValueError):
            bus.program64(1, b"\x5a" * 64)

    def test_aai256_capability_and_block_response(self):
        bus = transport.PicoTransport("COM1")
        bus.port.replies.append(b"CAPS AAI64 AAI256\n")
        self.assertTrue(bus.fast_aai256_available())
        bus.port.replies.append(b"AAI256 000100 OK\n")
        bus.program256(0x100, b"\x5a" * 256)
        self.assertEqual(bus.port.timeout, 2)
        self.assertEqual(len(bus.port.written[-1]), len("AAI256 000100 ") + 512 + 1)
        with self.assertRaises(ValueError):
            bus.program256(0x40, b"\x5a" * 256)

    def test_old_firmware_uses_legacy_writer(self):
        bus = transport.PicoTransport("COM1")
        bus.port.replies.append(b"ERR COMMAND\n")
        self.assertFalse(bus.fast_aai_available())
        self.assertFalse(bus.fast_aai_available())
        self.assertEqual(bus.port.written.count(b"CAPS\n"), 1)

    def test_power_cycle_nack_allows_direct_entry_attempt(self):
        calls = []

        def serial_factory(*args, **kwargs):
            port = FakePort(*args, **kwargs)
            if not calls:
                port.replies += [b"OK\n", b"OK\n"]  # PINS, RELEASE
            else:
                port.replies = [b"READY WAVEPOWER WAIT_POWER_OFF\n",
                                b"POWER_OFF_DETECTED WAIT_POWER_ON\n",
                                b"WAVEPOWER 0 ADDRESS_NACK\n"]
            calls.append(port)
            return port

        with patch.object(transport.serial, "Serial", serial_factory), \
             patch.object(transport.time, "sleep"):
            self.assertFalse(transport.PicoTransport.wait_power_cycle("COM1", (7, 6)))


if __name__ == "__main__": unittest.main()
