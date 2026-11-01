# SPDX-FileCopyrightText: 2026 R89 Repairs and contributors
# SPDX-License-Identifier: GPL-2.0-or-later

import tempfile
import unittest
from pathlib import Path
from app.ec import ECProbe, compare_reads, save_new, validate_image


class FakeBus:
    def __init__(self):
        self.writes = []
        self.reads = []
        self.values = iter((0x43, 0x55, 0x70))

    def wave(self): self.writes.append(("wave",))
    def write(self, addr, data): self.writes.append((addr, bytes(data)))
    def read(self, addr, count):
        self.reads.append((addr, count))
        if addr == 0x35: return bytes([next(self.values)])
        return bytes([len(self.reads) & 255]) * count


class ProtocolTests(unittest.TestCase):
    def test_identification_is_numeric_only(self):
        bus = FakeBus()
        self.assertEqual(ECProbe(bus).enter_and_identify(), (0x5570, 0x43))
        self.assertEqual(bus.writes[0], ("wave",))
        self.assertEqual(bus.writes[1], (0x5A, b"\x07"))
        self.assertIn((0x5A, b"\x02"), bus.writes)

    def test_read_boundary_and_length(self):
        bus = FakeBus()
        data = ECProbe(bus).read_flash(0x40000 + 256)
        self.assertEqual(len(data), 0x40000 + 256)
        self.assertEqual(bus.reads.count((0x79, 64)), 4100)
        self.assertEqual(bus.writes.count((0x5A, b"\x09")), 2)

    def test_backup_exclusive_and_comparison(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "backup.bin"
            self.assertEqual(len(save_new(p, b"abc")), 64)
            with self.assertRaises(FileExistsError): save_new(p, b"new")
            self.assertEqual(p.read_bytes(), b"abc")
            self.assertEqual(compare_reads(b"abc", b"axc")[2], 1)
            self.assertIsNone(compare_reads(b"abc", b"abc")[2])
            with self.assertRaises(ValueError): validate_image(p, 4)

    def test_size_rejected_before_io(self):
        bus = FakeBus()
        with self.assertRaises(ValueError): ECProbe(bus).read_flash(7)
        self.assertFalse(bus.writes)


if __name__ == "__main__": unittest.main()
