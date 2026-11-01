# SPDX-FileCopyrightText: 2026 R89 Repairs and contributors
# SPDX-License-Identifier: GPL-2.0-or-later

"""Check the ordering that matters for ITE AAI flash programming."""
import unittest

from app.ec import BLOCK, DATA, ECProbe
from app.flash_protocols import protocol_for

SUPPORTED_SIZE = 256 * 1024
LEGACY = protocol_for((0x8227, 0x02), bytes.fromhex("FF FF FE"))
V2 = protocol_for((0x8320, 0x03), bytes.fromhex("FF FF FE"))
KGD = protocol_for((0x8320, 0x03), bytes.fromhex("C8 00 00"))


class RecordingBus:
    def __init__(self):
        self.events = []

    def write(self, address, data):
        self.events.append(("write", address, bytes(data)))

    def read(self, address, count):
        self.events.append(("read", address, count))
        return b"\x02" * count  # WEL set, BUSY clear

    def read_page(self, address):
        self.events.append(("page", address))
        return b"\xff" * 256


class FlashProtocolTests(unittest.TestCase):
    def test_profile_identification_does_not_depend_on_flash_contents(self):
        self.assertEqual(LEGACY.program_method, "aai_legacy")
        self.assertEqual(V2.program_method, "aai_v2")
        self.assertEqual(KGD.program_method, "page_program")
        self.assertIsNone(protocol_for((0x8227, 0x02), bytes.fromhex("00 00 00")))

    def test_flash_id_can_be_read_from_data_register(self):
        class IdBus(RecordingBus):
            def read(self, address, count):
                self.events.append(("read", address, count))
                if address == BLOCK:
                    return b"\x00\x00\x00"
                if count == 3:
                    return b"\xC8\x00\x00"
                return b"\x02" * count

        profile = ECProbe(IdBus(), page_mode=True).flash_protocol((0x8320, 3))
        self.assertEqual(profile.name, "ITE eFlash KGD")

    def test_aai256_groups_four_blocks_and_skips_erased_pages(self):
        class FastBus:
            def __init__(self):
                self.blocks = []

            def fast_aai256_available(self):
                return True

            def program256(self, address, block):
                self.blocks.append((address, block))

        bus = FastBus()
        image = (b"\x12" * 64 + b"\xff" * 448 +
                 b"\x34" * 256 + b"\xff" * (SUPPORTED_SIZE - 768))
        ECProbe(bus, page_mode=True).write_flash(image, LEGACY)
        self.assertEqual(bus.blocks, [
            (0, b"\x12" * 64 + b"\xff" * 192),
            (512, b"\x34" * 256),
        ])

    def test_fast_firmware_receives_only_nonempty_blocks(self):
        class FastBus:
            def __init__(self):
                self.blocks = []

            def fast_aai_available(self):
                return True

            def program64(self, address, block):
                self.blocks.append((address, block))

        bus = FastBus()
        image = b"\x12" * 64 + b"\xff" * (SUPPORTED_SIZE - 64)
        ECProbe(bus, page_mode=True).write_flash(image, LEGACY)
        self.assertEqual(bus.blocks, [(0, b"\x12" * 64)])

    def test_legacy_aai_polls_before_quick_block_transfer(self):
        bus = RecordingBus()
        image = b"\x12\x34" + b"\xff" * (SUPPORTED_SIZE - 2)
        ECProbe(bus, page_mode=True).write_flash(image, LEGACY)
        events = bus.events
        aai = events.index(("write", DATA, b"\xad"))
        address_bytes = [i for i in range(aai + 1, len(events))
                         if events[i] == ("write", DATA, b"\x00")][:3]
        busy_poll = next(i for i in range(address_bytes[-1] + 1, len(events))
                         if events[i] == ("read", DATA, 1))
        quick_mode = events.index(("write", DATA, b"\x20"))
        first_block = next(i for i, event in enumerate(events)
                           if event[0] == "write" and event[1] == BLOCK)
        self.assertEqual(len(address_bytes), 3)
        self.assertLess(address_bytes[-1], busy_poll)
        self.assertLess(busy_poll, quick_mode)
        self.assertLess(quick_mode, first_block)
        self.assertEqual(sum(event[1] == BLOCK for event in events
                             if event[0] == "write"), 1)

    def test_erase_uses_all_256_one_kib_sectors(self):
        bus = RecordingBus()
        ECProbe(bus, page_mode=True).erase_flash(SUPPORTED_SIZE, LEGACY)
        self.assertEqual(sum(event == ("write", DATA, b"\xd7")
                             for event in bus.events), 256)

    def test_erase_geometry_uses_selected_capacity_and_flash_type(self):
        bus = RecordingBus()
        ECProbe(bus, page_mode=True).erase_flash(128 * 1024, KGD)
        self.assertGreaterEqual(sum(event == ("write", DATA, b"\x20")
                                    for event in bus.events), 32)
        self.assertNotIn(("write", DATA, b"\xd7"), bus.events)

    def test_v2_aai_sends_first_word_before_quick_block(self):
        bus = RecordingBus()
        ECProbe(bus, page_mode=True).write_flash(
            b"\x12\x34" + b"\xff" * (64 * 1024 - 2), V2)
        events = bus.events
        first_word = events.index(("write", DATA, b"\x12"))
        quick = events.index(("write", DATA, b"\x20"))
        block = events.index(("write", BLOCK, b"\xff" * 62))
        self.assertLess(first_word, quick)
        self.assertLess(quick, block)

    def test_kgd_programs_only_nonempty_64_byte_chunks(self):
        bus = RecordingBus()
        ECProbe(bus, page_mode=True).write_flash(
            b"\x12" * 64 + b"\xff" * (128 * 1024 - 64), KGD)
        self.assertEqual(sum(event == ("write", DATA, b"\x02")
                             for event in bus.events), 1)
        self.assertIn(("write", BLOCK, b"\x12" * 64), bus.events)

    def test_fast_v2_and_kgd_paths_skip_erased_chunks(self):
        class FastBus:
            def __init__(self):
                self.blocks = []

            def fast_aai_v2_available(self):
                return True

            def fast_page_available(self):
                return True

            def program_v2_64(self, address, block, page_program=False):
                self.blocks.append((address, block, page_program))

        bus = FastBus()
        image = b"\x12" * 64 + b"\xff" * (64 * 1024 - 64)
        ECProbe(bus, page_mode=True).write_flash(image, V2)
        ECProbe(bus, page_mode=True).write_flash(image, KGD)
        self.assertEqual(bus.blocks, [(0, b"\x12" * 64, False),
                                      (0, b"\x12" * 64, True)])

    def test_fast_v2_256_groups_blocks_and_skips_erased_pages(self):
        class FastBus:
            def __init__(self):
                self.blocks = []

            def fast_aai_v2_256_available(self):
                return True

            def program_v2_256(self, address, block):
                self.blocks.append((address, block))

        bus = FastBus()
        image = (b"\x12" * 64 + b"\xff" * 448 +
                 b"\x34" * 256 + b"\xff" * (128 * 1024 - 768))
        ECProbe(bus, page_mode=True).write_flash(image, V2)
        self.assertEqual(bus.blocks, [
            (0, b"\x12" * 64 + b"\xff" * 192),
            (512, b"\x34" * 256),
        ])


if __name__ == "__main__":
    unittest.main()
