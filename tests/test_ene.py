# SPDX-FileCopyrightText: 2026 R89 Repairs and contributors
# SPDX-License-Identifier: GPL-2.0-or-later

import unittest
from unittest.mock import patch

from app.ec import FlashError
from app.ene import EneEC, EneFlashProtocol, FLASH_SIZE
from app.operations import Worker
from app.models import FAMILIES_BY_MANUFACTURER
from app.transport import TransportError


class FakeBus:
    commands = []

    def __init__(self, *args, **kwargs):
        self.closed = False

    def command(self, command):
        self.commands.append(command)
        if command == "CAPS":
            return "CAPS AAI64 ENE_EDI"
        if command == "ENEOPEN":
            return "ENEOPEN HW=D0 EDI=0B"
        if command.startswith("ENEREADPAGE "):
            address = int(command.split()[1], 16)
            return f"ENEPAGE {address:05X} " + "A5" * 128
        if command.startswith("ENEERASEPAGE "):
            return command + " OK"
        if command.startswith("ENEWRITEPAGE "):
            return " ".join(command.split()[:2]) + " OK"
        raise AssertionError(command)

    def close(self):
        self.closed = True


class EneTests(unittest.TestCase):
    def setUp(self):
        FakeBus.commands = []
        self.bus = FakeBus()
        self.ec = EneEC(self.bus)

    def test_identify_requires_supported_edi_id(self):
        self.assertEqual(self.ec.enter_and_identify(), (0xD0, 0x0B))
        self.assertEqual(self.ec.flash_protocol((0xD0, 0x0B)), EneFlashProtocol())
        with patch.object(self.bus, "command", side_effect=("CAPS ENE_EDI", "ENEOPEN HW=FF EDI=FF")):
            with self.assertRaises(FlashError):
                self.ec.enter_and_identify()

    def test_read_and_verify_exact_128_kib(self):
        self.ec.enter_and_identify()
        progress = []
        image = self.ec.read_flash(FLASH_SIZE, lambda done, total: progress.append(done))
        self.assertEqual(len(image), FLASH_SIZE)
        self.assertEqual(image[:128], bytes([0xA5]) * 128)
        self.assertEqual(progress[-1], FLASH_SIZE)
        self.ec.verify_flash(image)
        with self.assertRaises(FlashError):
            self.ec.verify_flash(bytes(FLASH_SIZE))

    def test_wrong_size_prevents_destructive_commands(self):
        protocol = self.ec.flash_protocol((0xD0, 0x0B))
        with self.assertRaises(FlashError):
            self.ec.erase_flash(256 * 1024, protocol)
        with self.assertRaises(FlashError):
            self.ec.write_flash(bytes(64 * 1024), protocol)
        self.assertFalse(any(c.startswith("ENEERASEPAGE") or c.startswith("ENEWRITEPAGE")
                             for c in FakeBus.commands))

    def test_worker_connect_uses_ene_backend(self):
        profile = FAMILIES_BY_MANUFACTURER["ENE"][0]
        worker = Worker("connect", "COM1", (7, 6), profile)
        finished, failed = [], []
        worker.finished.connect(lambda action, result: finished.append((action, result)))
        worker.failed.connect(failed.append)
        with patch("app.operations.PicoTransport", FakeBus):
            worker.run()
        self.assertEqual(failed, [])
        self.assertEqual(finished[0][0], "connect")
        self.assertEqual(finished[0][1][0], (0xD0, 0x0B))
        self.assertEqual(finished[0][1][2].program_method, "ene_page")
        self.assertNotIn("PINS 7 6", FakeBus.commands)


if __name__ == "__main__":
    unittest.main()
