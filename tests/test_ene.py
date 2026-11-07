# SPDX-FileCopyrightText: 2026 R89 Repairs and contributors
# SPDX-License-Identifier: GPL-2.0-or-later

import unittest
from unittest.mock import patch

from app.ec import FlashError
from app.ene import EneEC, EneFlashProtocol
from app.ene_families import ENE_FAMILIES
from app.operations import Worker
from app.models import FAMILIES_BY_MANUFACTURER, Family
from app.ene_models import ENE_MODELS
from app.transport import TransportError
FLASH_SIZE = 128 * 1024


class FakeBus:
    commands = []
    identity = (0xD0, 0x0B)

    def __init__(self, *args, **kwargs):
        self.closed = False
        self.memory = bytearray([0xA5]) * (160 * 1024)

    def command(self, command):
        self.commands.append(command)
        if command == "CAPS":
            return "CAPS AAI64 ENE_EDI ENE_EDI_V2"
        if command.startswith("ENEOPEN "):
            return f"ENEOPEN HW={self.identity[0]:02X} EDI={self.identity[1]:02X}"
        if command.startswith("ENEREADPAGE "):
            address = int(command.split()[1], 16)
            return f"ENEPAGE {address:05X} " + self.memory[address:address+128].hex().upper()
        if command.startswith("ENEERASEPAGE "):
            address = int(command.split()[1], 16)
            self.memory[address:address+128] = bytes(128)
            return command + " OK"
        if command.startswith("ENEWRITEPAGE "):
            _, address, data = command.split()
            address = int(address, 16)
            self.memory[address:address+128] = bytes.fromhex(data)
            return " ".join(command.split()[:2]) + " OK"
        raise AssertionError(command)

    def close(self):
        self.closed = True


class EneTests(unittest.TestCase):
    def setUp(self):
        FakeBus.commands = []
        FakeBus.identity = (0xD0, 0x0B)
        self.bus = FakeBus()
        self.ec = EneEC(self.bus)

    def test_identify_requires_supported_edi_id(self):
        self.assertEqual(self.ec.enter_and_identify(), (0xD0, 0x0B))
        self.assertEqual(self.ec.flash_protocol((0xD0, 0x0B)), EneFlashProtocol("KB9052 (B/D)", (0xD0, 0x0B)))
        with patch.object(self.bus, "command", side_effect=("CAPS ENE_EDI_V2", "ENEOPEN HW=FF EDI=FF")):
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
        self.ec.enter_and_identify()
        protocol = self.ec.flash_protocol((0xD0, 0x0B))
        with self.assertRaises(FlashError):
            self.ec.erase_flash(256 * 1024, protocol)
        with self.assertRaises(FlashError):
            self.ec.write_flash(bytes(64 * 1024), protocol)
        self.assertFalse(any(c.startswith("ENEERASEPAGE") or c.startswith("ENEWRITEPAGE")
                             for c in FakeBus.commands))

    def test_worker_connect_uses_ene_backend(self):
        profile = FAMILIES_BY_MANUFACTURER["ENE"][-1]
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

    def test_all_family_signatures_share_flash_engine(self):
        for family in ENE_FAMILIES:
            for identity in family.identities:
                with self.subTest(family=family.name, identity=identity):
                    bus = FakeBus()
                    bus.identity = identity
                    ec = EneEC(bus, family=family.name)
                    self.assertEqual(ec.enter_and_identify(), identity)
                    self.assertIn(f"ENEOPEN {family.command}", bus.commands)
                    self.assertEqual(ec.flash_protocol(identity).program_method, "ene_page")

    def test_exact_models_resolve_to_shared_protocol_and_check_identity(self):
        for model in ENE_MODELS:
            bus = FakeBus()
            bus.identity = next(iter(model.identities)) if model.identities else (0x42, 0x07)
            ec = EneEC(bus, model.name)
            self.assertEqual(ec.enter_and_identify(), bus.identity)
            family = next(f for f in ENE_FAMILIES if f.name == model.family)
            self.assertIn(f"ENEOPEN {family.command}", bus.commands)
        bus = FakeBus()
        bus.identity = (0xC0, 0x07)
        with self.assertRaises(FlashError):
            EneEC(bus, "KB9022Q").enter_and_identify()

    def test_provisional_kb902fq_identity_and_flash_range(self):
        self.bus.identity = (0x42, 0x07)  # Synthetic, not a measured KB902FQ ID.
        ec = EneEC(self.bus, "KB902FQ C")
        protocol = ec.flash_protocol(ec.enter_and_identify())
        image = bytes(range(256)) * 512
        ec.erase_flash(FLASH_SIZE, protocol)
        ec.write_flash(image, protocol)
        ec.verify_flash(image)
        self.assertEqual(ec.read_flash(FLASH_SIZE), image)
        self.assertEqual(self.bus.memory[FLASH_SIZE:], bytes([0xA5]) * (32 * 1024))
        with self.assertRaises(FlashError):
            ec.read_flash(160 * 1024)
        for identity in ((0, 7), (255, 7), (0xA0, 7), (0xF0, 7), (0x42, 4), (0x42, 11)):
            self.bus.identity = identity
            with self.subTest(identity=identity), self.assertRaises(FlashError):
                EneEC(self.bus, "KB902FQ C").enter_and_identify()

    def test_wrong_family_rejected_even_if_firmware_reports_success(self):
        ec = EneEC(self.bus, family="KB901x")
        with self.assertRaisesRegex(FlashError, "does not match"):
            ec.enter_and_identify()
        with self.assertRaises(FlashError):
            ec.read_flash(FLASH_SIZE)
        self.assertFalse(any("PAGE " in command for command in self.bus.commands))

    def test_old_firmware_rejected_before_open(self):
        with patch.object(self.bus, "command", return_value="CAPS ENE_EDI") as command:
            with self.assertRaisesRegex(TransportError, "ENE_EDI_V2"):
                self.ec.enter_and_identify()
            command.assert_called_once_with("CAPS")

    def test_erase_write_verify_cover_last_160_kib_page(self):
        self.bus.identity = (0xF0, 0x07)
        ec = EneEC(self.bus, "KB9542GF")
        protocol = ec.flash_protocol(ec.enter_and_identify())
        size = 160 * 1024
        image = bytes(range(256)) * (size // 256)
        progress = []
        ec.erase_flash(size, protocol)
        self.assertEqual(self.bus.memory, bytes(size))
        ec.write_flash(image, protocol, lambda done, total: progress.append((done, total)))
        ec.verify_flash(image)
        self.assertEqual(ec.read_flash(size), image)
        self.assertEqual(progress[-1], (size, size))
        self.assertIn("ENEERASEPAGE 27F80", self.bus.commands)
        self.assertIn("ENEREADPAGE 27F80", self.bus.commands)
        self.assertTrue(any(command.startswith("ENEWRITEPAGE 27F80 ") for command in self.bus.commands))

    def test_fixed_160_kib_group_rejects_partial_operations_before_flash_access(self):
        self.bus.identity = (0xA0, 0x07)
        ec = EneEC(self.bus, "KB9542GF")
        protocol = ec.flash_protocol(ec.enter_and_identify())
        for operation in (lambda: ec.read_flash(FLASH_SIZE),
                          lambda: ec.erase_flash(FLASH_SIZE, protocol),
                          lambda: ec.write_flash(bytes(FLASH_SIZE), protocol),
                          lambda: ec.verify_flash(bytes(FLASH_SIZE))):
            with self.assertRaises(FlashError):
                operation()
        self.assertFalse(any("PAGE " in command for command in self.bus.commands))

    def test_stale_protocol_is_rejected_before_erase(self):
        self.ec.enter_and_identify()
        stale = EneFlashProtocol("KB9052 (B/D)", (0xB0, 0x0B))
        with self.assertRaises(FlashError):
            self.ec.erase_flash(FLASH_SIZE, stale)
        self.assertFalse(any(command.startswith("ENEERASEPAGE") for command in self.bus.commands))

    def test_worker_160_kib_read_and_ite_rejection_before_usb(self):
        profile = Family("KB9542GF", True, "ene_edi")
        FakeBus.identity = (0xF0, 0x07)
        worker = Worker("read", "SIMULATED", (7, 6), profile, FakeBus.identity, read_size=160*1024)
        finished, failed = [], []
        worker.finished.connect(lambda action, result: finished.append((action, result)))
        worker.failed.connect(failed.append)
        with patch("app.operations.PicoTransport", FakeBus):
            worker.run()
        self.assertEqual(failed, [])
        self.assertEqual(len(finished[0][1][1]), 160*1024)
        worker = Worker("erase", "SIMULATED", (7, 6), FAMILIES_BY_MANUFACTURER["ITE"][-1],
                        (0x8227, 3), read_size=160*1024)
        worker.failed.connect(failed.append)
        with patch("app.operations.PicoTransport") as transport:
            worker.run()
            transport.assert_not_called()
        self.assertEqual(len(failed), 1)


if __name__ == "__main__":
    unittest.main()
