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


class GuiLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        with patch("app.gui.ports", return_value=[("SIMULATED", "Test only")]):
            self.window = Window()
        self.window.flash_size.setCurrentIndex(4)
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


if __name__ == "__main__":
    unittest.main()
