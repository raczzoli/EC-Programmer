# SPDX-FileCopyrightText: 2026 R89 Repairs and contributors
# SPDX-License-Identifier: GPL-2.0-or-later

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch, Mock
from PySide6.QtCore import QThread
from PySide6.QtWidgets import QApplication, QMessageBox
from app.gui import Window
from app.ene import EneFlashProtocol


class GuiLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        with patch("app.gui.ports", return_value=[("SIMULATED", "Test only")]):
            self.window = Window()
        self.window.manufacturer.setCurrentText("ITE")
        self.window.model.setCurrentText("IT8xxx")
        self.window.flash_size.setValue(256)
        self.window.connected_identity = (0x8227, 3)
        self.window.connected_protocol = SimpleNamespace(name="test", program_method="aai_v2")
        self.window.update_buttons()

    def tearDown(self):
        self.window.reset_identity()
        self.window.close()
        self.window.deleteLater()
        self.app.processEvents()

    def test_keepalive_owns_usb_off_gui_thread(self):
        calls = []
        class Session:
            def __init__(self, *args):
                pass
            def refresh(self, identity):
                calls.append(("refresh", QThread.currentThread() == QApplication.instance().thread()))
                return identity
            def close(self):
                calls.append(("close", QThread.currentThread() == QApplication.instance().thread()))
        status = self.window.status.text()
        with patch("app.operations.DeviceSession", Session):
            self.window.refresh_debug_hold()
            deadline = time.monotonic() + 5
            while self.window.thread is not None and time.monotonic() < deadline:
                self.app.processEvents()
                time.sleep(0.001)
        self.assertIsNone(self.window.thread)
        self.assertEqual(calls, [("refresh", False), ("close", False)])
        self.assertEqual(self.window.status.text(), status)
        self.assertTrue(self.window.write.isEnabled())

    def test_failure_invalidates_all_flash_buttons(self):
        self.window.worker = SimpleNamespace(action="read")
        self.window.on_failed("USB disconnected")
        self.assertIsNone(self.window.connected_identity)
        self.assertFalse(self.window.read.isEnabled())
        self.assertFalse(self.window.write.isEnabled())
        self.assertFalse(self.window.erase.isEnabled())
        self.assertFalse(self.window.keepalive.isActive())

    def test_power_cycle_prompt_closes_when_operation_fails(self):
        self.window.worker = SimpleNamespace(action="connect")
        self.window.show_power_cycle_prompt()
        self.assertIsNotNone(self.window.power_prompt)
        self.window.on_failed("No ACK")
        self.assertIsNone(self.window.power_prompt)

    def test_flash_operation_waits_for_keepalive_started_during_dialog(self):
        def confirm(*args):
            self.window.thread = Mock()
            self.window.worker = SimpleNamespace(action="keepalive")
            return QMessageBox.StandardButton.Yes
        with patch("app.gui.QMessageBox.question", side_effect=confirm):
            self.window.start("erase")
        self.assertEqual(self.window.worker.action, "keepalive")
        self.assertEqual(self.window._pending_operation, ("erase", None))
        with patch.object(self.window, "start") as start:
            self.window.on_thread_finished()
            start.assert_called_once_with("erase", None, confirmed=True)
        self.assertIsNone(self.window._pending_operation)

    def test_ene_models_fixed_size_and_buttons(self):
        self.window.manufacturer.setCurrentText("ENE")
        self.assertEqual([self.window.model.itemText(i) for i in range(self.window.model.count())],
                         ["KB9012QF", "KB9022Q", "KB9028Q", "KB9052QD"])
        for family in ("KB9012QF", "KB9022Q", "KB9028Q", "KB9052QD"):
            self.window.model.setCurrentText(family)
            self.assertEqual(self.window.flash_size.value(), 128)
            self.assertFalse(self.window.flash_size.isEnabled())
        self.window.model.setCurrentText("KB9052QD")
        self.assertEqual(self.window.flash_size.value(), 128)
        self.assertFalse(self.window.flash_size.isEnabled())
        identity = (0xD0, 0x0B)
        protocol = EneFlashProtocol("KB9052QD", identity)
        self.window.on_finished("connect", (identity, False, protocol))
        self.assertTrue(self.window.read.isEnabled())
        self.assertTrue(self.window.write.isEnabled())
        self.assertTrue(self.window.erase.isEnabled())
        self.assertIn("KB9052QD (experimental)", self.window.identity.text())
        self.assertIn("128 KiB (family)", self.window.identity.text())
        self.assertFalse(self.window.keepalive.isActive())
        # Busy/idle transitions must not accidentally unlock a fixed size.
        self.window.thread = Mock()
        self.window.update_buttons()
        self.window.thread = None
        self.window.update_buttons()
        self.assertFalse(self.window.flash_size.isEnabled())
        self.window.flash_size.setValue(160)
        self.assertEqual(self.window.flash_size_bytes(), 128*1024)
        self.window.manufacturer.setCurrentText("ITE")
        self.assertIsNone(self.window.model.currentData())
        self.assertFalse(self.window.detect.isEnabled())
        self.window.model.setCurrentText("IT8xxx")
        self.assertTrue(self.window.flash_size.isEnabled())
        self.assertEqual(self.window.flash_size.value(), 256)
        self.assertIsNone(self.window.connected_identity)

    def test_ite_numeric_input_rejects_unsupported_ranges_and_uses_bytes(self):
        self.window.flash_size.setValue(160)
        self.assertFalse(self.window.read.isEnabled())
        self.assertFalse(self.window.write.isEnabled())
        self.assertFalse(self.window.erase.isEnabled())
        self.assertIn("unsupported size", self.window.identity.text())
        self.window.flash_size.setValue(128)
        self.assertTrue(self.window.read.isEnabled())
        self.assertTrue(self.window.write.isEnabled())
        self.assertEqual(self.window.flash_size_bytes(), 128*1024)
        self.window.flash_size.stepUp()
        self.assertEqual(self.window.flash_size_bytes(), 192*1024)

    def test_model_pinout_and_phase_colors(self):
        self.window.manufacturer.setCurrentText("ENE")
        self.assertEqual(self.window.ene_wiring.text(), "")
        self.assertIsNone(self.window.create_wiring_dialog())
        for model in ("KB9012QF", "KB9022Q", "KB9028Q", "KB9052QD"):
            self.window.model.setCurrentText(model)
            self.assertIn("View wiring diagram", self.window.ene_wiring.text())
            from app.wiring_diagram import WiringDiagram
            dialog = self.window.create_wiring_dialog()
            diagram = dialog.findChild(WiringDiagram)
            self.assertEqual(diagram.model.name, model)
            self.assertIn("GP4 = EC pin 62", diagram.accessibleName())
            self.assertIn("EC pin 42 (KSO3)", diagram.accessibleName())
            dialog.deleteLater()
        for phase, color in (("Read", "#15803d"), ("Erase", "#dc2626"),
                             ("Programming", "#ea580c"), ("Verification", "#15803d")):
            self.window.set_progress_phase(phase)
            self.assertIn(color, self.window.progress.styleSheet())

    def test_ene_read_filename_uses_selected_group(self):
        self.window.manufacturer.setCurrentText("ENE")
        self.window.model.setCurrentText("KB9022Q")
        self.window.pending_read = bytes(128)
        self.window.pending_identity = (0xB1, 0x07)
        try:
            with patch("app.gui.QFileDialog.getSaveFileName", return_value=("", "")) as save:
                self.window.save_read()
            self.assertIn("ENE-KB9022Q-HWB1", save.call_args.args[2])
        finally:
            self.window.pending_read = self.window.pending_identity = None


if __name__ == "__main__":
    unittest.main()
