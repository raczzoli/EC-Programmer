# SPDX-FileCopyrightText: 2026 R89 Repairs and contributors
# SPDX-License-Identifier: GPL-2.0-or-later

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.gui import Worker, resolve_read_size
from app.transport import TransportError


class FakeBus:
    def __init__(self, *args, **kwargs):
        self.closed = False

    def pins(self, *pins):
        pass

    def command(self, command):
        if command == "HOLDDBGR":
            return "HOLDDBGR ACTIVE"
        raise AssertionError(command)

    def close(self):
        self.closed = True


class ReadSessionTests(unittest.TestCase):
    def run_worker(self, identify, action="read", enter_error_count=0,
                   read_size=256 * 1024):
        worker = Worker(action, "COM1", (7, 6),
                        SimpleNamespace(read_protocol=True), (0x8227, 2),
                        read_size=read_size)
        finished, failed = [], []
        self.read_sizes = []
        read_sizes = self.read_sizes
        entry_calls = [0]
        worker.finished.connect(lambda action, result: finished.append((action, result)))
        worker.failed.connect(failed.append)

        class FakeEC:
            def __init__(self, bus, page_mode):
                pass

            def identify(self):
                if isinstance(identify, Exception):
                    raise identify
                return identify

            def enter_and_identify(self):
                entry_calls[0] += 1
                if entry_calls[0] <= enter_error_count:
                    raise TransportError("ERR ENTERDBGR_NO_ACK ADDRESS_NACK")
                return (0x8227, 2)

            def read_flash(self, size, progress):
                read_sizes.append(size)
                progress(size, size)
                return b"backup"

            def flash_protocol(self, identity):
                return SimpleNamespace(name="ITE eFlash 8315",
                                       program_method="aai_legacy")

        with patch("app.gui.PicoTransport", FakeBus), \
             patch("app.gui.ECProbe", FakeEC), \
             patch.object(FakeBus, "wait_power_cycle", create=True) as wait, \
             patch("app.gui.time.sleep"):
            worker.run()
        return finished, failed, wait.call_count

    def test_reuses_active_debug_session(self):
        finished, failed, cycles = self.run_worker((0x8227, 2))
        self.assertEqual(failed, [])
        self.assertEqual(finished, [("read", ((0x8227, 2), b"backup"))])
        self.assertEqual(cycles, 0)

    def test_manual_128_kib_reaches_page_reader(self):
        finished, failed, _ = self.run_worker((0x8227, 2), read_size=128 * 1024)
        self.assertEqual(failed, [])
        self.assertEqual(finished[0][0], "read")
        self.assertEqual(self.read_sizes, [128 * 1024])

    def test_read_requires_explicit_size(self):
        with self.assertRaises(ValueError):
            resolve_read_size(None)
        self.assertEqual(resolve_read_size(64 * 1024), 64 * 1024)
        self.assertEqual(resolve_read_size(192 * 1024), 192 * 1024)
        self.assertEqual(resolve_read_size(256 * 1024), 256 * 1024)
        with self.assertRaises(ValueError):
            resolve_read_size(512 * 1024)

    def test_direct_entry_after_address_nack_avoids_power_cycle(self):
        finished, failed, cycles = self.run_worker(TransportError("ERR ADDRESS_NACK"))
        self.assertEqual(failed, [])
        self.assertEqual(finished[0][0], "read")
        self.assertEqual(cycles, 0)

    def test_connect_reuses_active_session(self):
        finished, failed, cycles = self.run_worker((0x8227, 2), "connect")
        self.assertEqual(failed, [])
        self.assertEqual(finished[0][0], "connect")
        self.assertEqual(finished[0][1][0], (0x8227, 2))
        self.assertEqual(finished[0][1][2].name, "ITE eFlash 8315")
        self.assertEqual(cycles, 0)

    def test_connect_recovers_expired_session(self):
        finished, failed, cycles = self.run_worker(
            TransportError("ERR ADDRESS_NACK"), "connect", enter_error_count=1
        )
        self.assertEqual(failed, [])
        self.assertEqual(finished[0][0], "connect")
        self.assertEqual(finished[0][1][0], (0x8227, 2))
        self.assertEqual(finished[0][1][2].name, "ITE eFlash 8315")
        self.assertEqual(cycles, 1)

    def test_connect_retries_nack_after_one_power_cycle(self):
        finished, failed, cycles = self.run_worker(
            TransportError("ERR ADDRESS_NACK"), "connect", enter_error_count=2
        )
        self.assertEqual(failed, [])
        self.assertEqual(finished[0][0], "connect")
        self.assertEqual(finished[0][1][0], (0x8227, 2))
        self.assertEqual(finished[0][1][2].name, "ITE eFlash 8315")
        self.assertEqual(cycles, 1)

    def test_unpowered_scl_timeout_can_arm_one_power_cycle(self):
        finished, failed, cycles = self.run_worker(
            TransportError("ERR SCL_LOW_TIMEOUT"), "connect", enter_error_count=1
        )
        self.assertEqual(failed, [])
        self.assertEqual(finished[0][0], "connect")
        self.assertEqual(cycles, 1)


if __name__ == "__main__":
    unittest.main()
