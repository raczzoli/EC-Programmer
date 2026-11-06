# SPDX-FileCopyrightText: 2026 R89 Repairs and contributors
# SPDX-License-Identifier: GPL-2.0-or-later

"""Check Write/Erase ordering without touching a real EC."""
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app.operations import Worker
from app.transport import TransportError


class FakeBus:
    def __init__(self, *args, **kwargs):
        pass

    def pins(self, *pins):
        pass

    def close(self):
        pass


class WriteSafetyTests(unittest.TestCase):
    def run_operation(self, root, action="write", image_size=256 * 1024,
                      selected_size=256 * 1024, bus_class=FakeBus, fail_write=False):
        image = root / "image.bin"
        image.write_bytes(b"\x5a" * image_size)
        events, finished, failed = [], [], []
        self.warnings, self.terminal_events = [], []
        worker = Worker(action, "COM1", (7, 6),
                        SimpleNamespace(read_protocol=True), (0x8227, 2),
                        str(image) if action == "write" else None,
                        selected_size)
        worker.finished.connect(lambda name, result: finished.append((name, result)))
        worker.failed.connect(failed.append)
        self.phases = []
        worker.phase.connect(self.phases.append)
        self.progress_events = []
        worker.phase.connect(lambda phase: self.progress_events.append((phase, None)))
        worker.progress.connect(lambda value: self.progress_events.append((self.phases[-1], value)))
        worker.finished.connect(lambda *args: self.terminal_events.append("finished"))
        worker.failed.connect(lambda *args: self.terminal_events.append("failed"))
        worker.warning.connect(self.warnings.append)
        worker.warning.connect(lambda *args: self.terminal_events.append("warning"))

        class FakeEC:
            def __init__(self, bus, page_mode):
                pass

            def identify(self):
                return 0x8227, 2

            def flash_protocol(self, identity):
                events.append("profile")
                return SimpleNamespace(name="ITE eFlash 8315",
                                       program_method="aai_legacy")

            def read_flash(self, size, progress):
                events.append("unexpected_read")
                raise AssertionError("Write and Erase must not read a backup")

            def erase_flash(self, size, protocol, progress):
                events.append("erase")
                progress(size, size)

            def verify_flash(self, expected, progress):
                events.append("verify_image")
                progress(len(expected), len(expected))

            def write_flash(self, data, protocol, progress):
                events.append("write")
                if fail_write:
                    raise TransportError("write failure")
                progress(len(data), len(data))

        with patch("app.operations.PicoTransport", bus_class), patch("app.operations.ECProbe", FakeEC):
            worker.run()
        return events, finished, failed

    def test_write_erases_programs_and_verifies_without_backup(self):
        with tempfile.TemporaryDirectory() as directory:
            events, finished, failed = self.run_operation(Path(directory))
            self.assertEqual(failed, [])
            self.assertEqual(events, ["profile", "erase", "write", "verify_image"])
            self.assertEqual(finished, [("write", (0x8227, 2))])
            self.assertEqual(self.phases, ["Erase", "Programming", "Verification"])
            self.assertEqual(self.progress_events, [(phase, value)
                for phase in ("Erase", "Programming", "Verification") for value in (None, 0, 100)])

    def test_erase_only_erases_without_read_or_verify(self):
        with tempfile.TemporaryDirectory() as directory:
            events, finished, failed = self.run_operation(Path(directory), "erase")
            self.assertEqual(failed, [])
            self.assertEqual(events, ["profile", "erase"])
            self.assertEqual(finished, [("erase", (0x8227, 2))])
            self.assertEqual(self.phases, ["Erase"])

    def test_wrong_image_size_stops_before_erase(self):
        with tempfile.TemporaryDirectory() as directory:
            events, finished, failed = self.run_operation(Path(directory), image_size=17)
            self.assertEqual(events, [])
            self.assertEqual(finished, [])
            self.assertIn("Image must be", failed[0])

    def test_128_kib_write_uses_selected_capacity(self):
        with tempfile.TemporaryDirectory() as directory:
            events, finished, failed = self.run_operation(
                Path(directory), image_size=128 * 1024,
                selected_size=128 * 1024)
            self.assertEqual(failed, [])
            self.assertEqual(events, ["profile", "erase", "write", "verify_image"])

    def test_writer_capability_failure_happens_before_erase(self):
        class BadCaps(FakeBus):
            def fast_aai256_available(self):
                raise TransportError("CAPS timeout")
        with tempfile.TemporaryDirectory() as directory:
            events, finished, failed = self.run_operation(Path(directory), bus_class=BadCaps)
        self.assertEqual(events, ["profile"])
        self.assertFalse(finished)
        self.assertIn("CAPS timeout", failed[0])
        self.assertNotIn("after erase", failed[0])

    def test_cleanup_error_does_not_turn_verified_write_into_second_result(self):
        class BadClose(FakeBus):
            def close(self):
                raise TransportError("cleanup failure")
        with tempfile.TemporaryDirectory() as directory:
            events, finished, failed = self.run_operation(Path(directory), bus_class=BadClose)
        self.assertEqual(events[-1], "verify_image")
        self.assertEqual(len(finished), 1)
        self.assertEqual(failed, [])
        self.assertEqual(self.terminal_events, ["finished", "warning"])
        self.assertIn("cleanup failure", self.warnings[0])

    def test_write_and_cleanup_failure_preserve_primary_error(self):
        class BadClose(FakeBus):
            def close(self):
                raise TransportError("cleanup failure")
        with tempfile.TemporaryDirectory() as directory:
            events, finished, failed = self.run_operation(
                Path(directory), bus_class=BadClose, fail_write=True)
        self.assertEqual(events[-1], "write")
        self.assertFalse(finished)
        self.assertIn("after erase began", failed[0])
        self.assertIn("write failure", failed[0])
        self.assertEqual(self.terminal_events, ["failed", "warning"])


if __name__ == "__main__":
    unittest.main()
