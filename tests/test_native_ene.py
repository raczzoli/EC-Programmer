# SPDX-FileCopyrightText: 2026 R89 Repairs and contributors
# SPDX-License-Identifier: GPL-2.0-or-later

"""Production ENE firmware against a register-level simulator, never USB."""
import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from app.ene_families import ENE_FAMILIES

ROOT = Path(__file__).resolve().parents[1]


class NativeEneTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if importlib.util.find_spec("ziglang"):
            compiler = [sys.executable, "-m", "ziglang", "cc"]
        else:
            cc = os.environ.get("CC") or shutil.which("cc") or shutil.which("gcc")
            if not cc:
                raise RuntimeError("Native ENE tests need a C compiler or ziglang")
            compiler = [cc]
        cls.temp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temp.cleanup)
        cls.exe = Path(cls.temp.name) / ("ene-test.exe" if os.name == "nt" else "ene-test")
        subprocess.run(compiler + ["-std=c11", "-Wall", "-Wextra", "-Werror",
                       "-Itests/native", "-Ifirmware", "tests/native/ene_harness.c",
                       "firmware/ene_edi.c", "-o", str(cls.exe)], cwd=ROOT, check=True,
                       capture_output=True, text=True, timeout=180)

    def run_c(self, family="KB9052", hw=0xD0, ediid=0x0B, fault="normal", size=128*1024):
        return subprocess.check_output([str(self.exe), family, f"{hw:02X}", f"{ediid:02X}",
                                        fault, str(size)], text=True, timeout=10).splitlines()

    def test_all_documented_groups_roundtrip_and_address_boundaries(self):
        for group in ENE_FAMILIES:
            for hw, ediid in group.identities:
                with self.subTest(family=group.name, hw=hw):
                    trace = self.run_c(group.command, hw, ediid, size=max(group.sizes))
                    self.assertIn(f"ROUNDTRIP {max(group.sizes)} ERASES=4 PROGRAMS=4 BOUNDS_OK", trace)
                    self.assertEqual(trace[-1], "CLOSE=1 PINS_RELEASED")
                    self.assertIn("WDT=1 VALUE=48" if hw==0xF0 else "WDT=0 VALUE=00", trace[0])

    def test_provisional_kb902fq_roundtrip_bounds_and_identity_retention(self):
        # Synthetic identity: no measured KB902FQ hardware ID is available yet.
        trace = self.run_c("KB902FQ", 0x42, 7)
        self.assertIn("ROUNDTRIP 131072 ERASES=4 PROGRAMS=4 BOUNDS_OK", trace)
        self.assertIn("WDT=0 VALUE=00", trace[0])
        self.assertIn("ID_CHANGED", self.run_c("KB902FQ", 0x42, 7, "idchange"))
        for hw, ediid in ((0, 7), (255, 7), (0xA0, 7), (0xF0, 7), (0x42, 4), (0x42, 11)):
            with self.subTest(hw=hw, ediid=ediid):
                trace = self.run_c("KB902FQ", hw, ediid)
                self.assertTrue(trace[0].startswith("OPEN_ERROR EDI_"))
                self.assertIn("RESET=0 WDT=0 CPU=0", trace[0])

    def test_wrong_group_and_unknown_revision_stop_before_cpu_or_flash_writes(self):
        for hw, ediid in ((0xC3, 0x04), (0x99, 0x0B)):
            trace = self.run_c(hw=hw, ediid=ediid)
            self.assertTrue(trace[0].startswith("OPEN_ERROR EDI_"))
            self.assertIn("RESET=0 WDT=0 CPU=0", trace[0])

    def test_noisy_absent_and_short_spi_responses_never_identify(self):
        for fault in ("noise", "notready", "short"):
            with self.subTest(fault=fault):
                self.assertEqual(self.run_c(fault=fault), ["OPEN_ERROR EDI_NO_DEVICE RESET=0 WDT=0 CPU=0"])

    def test_delayed_ready_and_initial_unavailable_reads_recover(self):
        for fault in ("delayed", "late", "ready_tail"):
            with self.subTest(fault=fault):
                self.assertEqual(self.run_c(fault=fault)[-1], "CLOSE=1 PINS_RELEASED")

    def test_failed_reset_never_opens_session(self):
        trace = self.run_c(fault="resetfail")
        self.assertTrue(trace[0].startswith("OPEN_ERROR EDI_CPU_RESET"))
        self.assertTrue(trace[0].endswith("WDT=0 CPU=0"))

    def test_failed_watchdog_configuration_releases_cpu_and_pins(self):
        trace = self.run_c("KB9542GF", 0xF0, 0x07, "wdtfail", 160*1024)
        self.assertTrue(trace[0].startswith("OPEN_ERROR EDI_WRITE_IO"))
        self.assertTrue(trace[0].endswith("WDT=1 CPU=0"))

    def test_session_loss_is_reported_before_or_during_page(self):
        self.assertIn("SESSION_LOST_BEFORE_FLASH", self.run_c(fault="lost"))
        self.assertIn("SESSION_LOST_DURING_READ", self.run_c(fault="midreset"))

    def test_busy_timeout_disables_flash_and_preserves_error(self):
        self.assertIn("BUSY_TIMEOUT_WRITE_DISABLED", self.run_c(fault="busy"))

    def test_changed_identity_is_not_reused(self):
        self.assertIn("ID_CHANGED", self.run_c(fault="idchange"))

    def test_failed_close_still_releases_gpio(self):
        self.assertEqual(self.run_c(fault="closefail")[-1], "CLOSE=0 PINS_RELEASED")
