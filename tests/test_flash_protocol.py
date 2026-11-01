"""Check the ordering that matters for ITE AAI flash programming."""
import unittest

from app.ec import BLOCK, DATA, ECProbe, SUPPORTED_SIZE
from app.flash_profiles import EFLASH_8315_256K, profile_for


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
        self.assertEqual(
            profile_for((0x8227, 0x02), bytes.fromhex("FF FF FE")),
            EFLASH_8315_256K,
        )
        self.assertIsNone(profile_for((0x8227, 0x03), bytes.fromhex("FF FF FE")))
        self.assertIsNone(profile_for((0x8227, 0x02), bytes.fromhex("00 00 00")))

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
        ECProbe(bus, page_mode=True).write_flash(image)
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
        ECProbe(bus, page_mode=True).write_flash(image)
        self.assertEqual(bus.blocks, [(0, b"\x12" * 64)])

    def test_legacy_aai_polls_before_quick_block_transfer(self):
        bus = RecordingBus()
        image = b"\x12\x34" + b"\xff" * (SUPPORTED_SIZE - 2)
        ECProbe(bus, page_mode=True).write_flash(image)
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
        ECProbe(bus, page_mode=True).erase_flash(SUPPORTED_SIZE)
        self.assertEqual(sum(event == ("write", DATA, b"\xd7")
                             for event in bus.events), 256)


if __name__ == "__main__":
    unittest.main()
