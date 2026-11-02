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

    def test_new_programming_capabilities_and_commands(self):
        bus = transport.PicoTransport("COM1")
        bus.port.replies.append(b"CAPS AAI64 AAI256 AAIV2_64 AAIV2_256 PAGE64\n")
        self.assertTrue(bus.fast_aai_v2_available())
        self.assertTrue(bus.fast_aai_v2_256_available())
        self.assertTrue(bus.fast_page_available())
        bus.port.replies.append(b"AAIV2_64 000040 OK\n")
        bus.program_v2_64(0x40, b"\x12" * 64)
        bus.port.replies.append(b"PAGE64 000080 OK\n")
        bus.program_v2_64(0x80, b"\x34" * 64, page_program=True)
        bus.port.replies.append(b"AAIV2_256 000100 OK\n")
        bus.program_v2_256(0x100, b"\x56" * 256)
        self.assertTrue(bus.port.written[-3].startswith(b"AAIV2_64 000040"))
        self.assertTrue(bus.port.written[-2].startswith(b"PAGE64 000080"))
        self.assertTrue(bus.port.written[-1].startswith(b"AAIV2_256 000100"))

    def test_old_firmware_uses_legacy_writer(self):
        bus = transport.PicoTransport("COM1")
        bus.port.replies.append(b"ERR COMMAND\n")
        self.assertFalse(bus.fast_aai_available())
        self.assertFalse(bus.fast_aai_available())
        self.assertEqual(bus.port.written.count(b"CAPS\n"), 1)

    def test_tagged_command_ignores_late_response(self):
        bus = transport.PicoTransport("COM1")
        bus.port.replies.append(b"CAPS TAGGED REGIO\n")
        self.assertTrue(bus.supports("REGIO"))
        bus._sequence = 10
        bus.port.replies += [b"DATA FF\n", b"@0000000A OK\n", b"@0000000B REG 02 03\n"]
        self.assertEqual(bus.reg_read(2), 3)
        self.assertEqual(bus.port.written[-1], b"@0000000B REGREAD 02\n")

    def test_timeout_prevents_release_or_further_commands(self):
        bus = transport.PicoTransport("COM1")
        with self.assertRaisesRegex(transport.TransportError, "Timeout"):
            bus.command("READPAGE 000000")
        written = list(bus.port.written)
        bus.port.replies.append(b"PAGE 000000 FF\n")
        with self.assertRaisesRegex(transport.TransportError, "out of sync"):
            bus.command("HELLO")
        bus.close()
        self.assertFalse(bus.port.is_open)
        self.assertEqual(bus.port.written, written)

    def test_partial_line_poisoned_and_no_release_queued(self):
        bus = transport.PicoTransport("COM1")
        bus.port.replies.append(b"AAI256 000100 O")
        with self.assertRaisesRegex(transport.TransportError, "incomplete"):
            bus.program256(0x100, b"\x42" * 256)
        bus.close()
        self.assertNotIn(b"RELEASE\n", bus.port.written)

    def test_release_cannot_accept_late_data_as_success(self):
        bus = transport.PicoTransport("COM1")
        bus.port.replies.append(b"DATA FF\n")
        with self.assertRaisesRegex(transport.TransportError, "RELEASE acknowledgement"):
            bus.close()
        self.assertFalse(bus.port.is_open)

    def test_handshake_discards_previous_commands_reply(self):
        port = FakePort()
        port.replies.insert(0, b"@00000001 AAI64 000000 OK\n")
        with patch.object(transport.serial, "Serial", return_value=port):
            bus = transport.PicoTransport("COM1")
        self.assertTrue(bus.port.is_open)

    def test_legacy_probe_handshake_accepts_crlf(self):
        port = FakePort()
        port.replies = [b"OK PICO_EC_PROBE 1 PROBE_ONLY\r\n"]
        with patch.object(transport.serial, "Serial", return_value=port):
            self.assertTrue(transport.PicoTransport("COM1").port.is_open)

    def test_bad_page_address_rejected_before_usb(self):
        bus = transport.PicoTransport("COM1")
        before = list(bus.port.written)
        for address in (-1, 1, 0x40000):
            with self.assertRaises(ValueError):
                bus.read_page(address)
        self.assertEqual(bus.port.written, before)

    def test_context_cleanup_does_not_replace_primary_error(self):
        bus = transport.PicoTransport("COM1")
        bus.port.replies.append(b"ERR CLEANUP\n")
        with self.assertRaisesRegex(RuntimeError, "primary failure"):
            with bus:
                raise RuntimeError("primary failure")

    def test_atomic_ite_replies_are_validated(self):
        bus = transport.PicoTransport("COM1")
        bus.port.replies += [b"STATUS 02\n", b"FLASHID FFFFFE\n",
                            b"SESSION CHIPID=8227 CHIPVER=03\n",
                            b"ERASESECTOR 000400 OK\n"]
        self.assertEqual(bus.spi_status(), 2)
        self.assertEqual(bus.flash_id(0x79), bytes.fromhex("FFFFFE"))
        self.assertEqual(bus.session(), (0x8227, 3))
        bus.erase_sector(0x400, 0xd7)
        bus.port.replies.append(b"ERASESECTOR 000000 OK\n")
        with self.assertRaises(transport.TransportError):
            bus.erase_sector(0x400, 0xd7)

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
