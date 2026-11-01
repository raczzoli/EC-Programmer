# SPDX-FileCopyrightText: 2026 R89 Repairs and contributors
# SPDX-License-Identifier: GPL-2.0-or-later

"""Windows GUI for ITE EC communication and staged flash operations."""

import hashlib
import sys
import time
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QObject, QThread, QTimer, Qt, Signal, Slot
from PySide6.QtWidgets import (
    QApplication, QComboBox, QFileDialog, QFrame, QGroupBox, QHBoxLayout,
    QLabel, QMainWindow, QMessageBox, QPlainTextEdit, QProgressBar, QPushButton,
    QScrollArea, QSizePolicy, QSpinBox, QVBoxLayout, QWidget,
)

from .ec import ECProbe, SUPPORTED_SIZE, save_new
from .models import FAMILIES_BY_MANUFACTURER
from .style import STYLESHEET
from .transport import PicoTransport, TransportError, ports

READ_WINDOW = 256 * 1024  # Current READPAGE firmware limit; not a capacity claim.


class Worker(QObject):
    progress = Signal(int)
    status = Signal(str)
    power_cycle_needed = Signal()
    finished = Signal(str, object)
    failed = Signal(str)

    def __init__(self, action, port, pins, profile, expected_identity=None, image_path=None):
        super().__init__()
        self.action, self.port, self.pins, self.profile = action, port, pins, profile
        self.expected_identity = expected_identity
        self.image_path = image_path

    def wait_for_target_reset(self):
        def power_status(message):
            self.status.emit(message)
            if message.startswith("Pico is armed:"):
                self.power_cycle_needed.emit()

        PicoTransport.wait_power_cycle(self.port, self.pins, power_status)

    @staticmethod
    def _bus_unavailable(exc):
        return any(part in str(exc) for part in
                   ("ADDRESS_NACK", "DATA_NACK", "SCL_LOW_TIMEOUT"))

    def enter_after_power_cycle(self, ec):
        """Give the powered EC time to accept DBGR without another unplug."""
        last_error = None
        for delay in (0, 0.5, 1, 2, 3, 4):
            if delay:
                time.sleep(delay)
            try:
                return ec.identify()
            except TransportError as exc:
                if not self._bus_unavailable(exc):
                    raise
            try:
                return ec.enter_and_identify()
            except TransportError as exc:
                if "ENTERDBGR_NO_ACK" not in str(exc):
                    raise
                last_error = exc
                self.status.emit("EC is powered but has not acknowledged DBGR; retrying...")
        raise last_error

    @Slot()
    def run(self):
        bus = None
        destructive_started = False
        try:
            page_mode = self.profile.read_protocol
            if page_mode and self.action in ("read", "write", "erase"):
                bus = PicoTransport(self.port, timeout=5)
                bus.pins(*self.pins)
                ec = ECProbe(bus, page_mode=True)
                try:
                    identity = ec.identify()
                except TransportError as exc:
                    if not self._bus_unavailable(exc):
                        raise
                    try:
                        identity = ec.enter_and_identify()
                    except TransportError as entry_error:
                        if "ENTERDBGR_NO_ACK" not in str(entry_error):
                            raise
                        bus.close()
                        bus = None
                        self.status.emit("EC debug entry needs a target reset.")
                        self.wait_for_target_reset()
                        bus = PicoTransport(self.port, timeout=5)
                        bus.pins(*self.pins)
                        ec = ECProbe(bus, page_mode=True)
                        identity = self.enter_after_power_cycle(ec)
                else:
                    self.status.emit("EC debug session is active; continuing without a power cycle.")
            else:
                bus = PicoTransport(self.port, timeout=5)
                bus.pins(*self.pins)
                ec = ECProbe(bus, page_mode=page_mode)
                if page_mode and self.action == "connect":
                    try:
                        identity = ec.identify()
                    except TransportError as exc:
                        if not self._bus_unavailable(exc):
                            raise
                        try:
                            identity = ec.enter_and_identify()
                        except TransportError as entry_error:
                            if "ENTERDBGR_NO_ACK" not in str(entry_error):
                                raise
                            bus.close()
                            bus = None
                            self.status.emit("EC debug entry needs a target reset.")
                            self.wait_for_target_reset()
                            bus = PicoTransport(self.port, timeout=5)
                            bus.pins(*self.pins)
                            ec = ECProbe(bus, page_mode=True)
                            identity = self.enter_after_power_cycle(ec)
                else:
                    identity = ec.enter_and_identify()
            if self.action != "connect" and self.expected_identity != identity:
                raise RuntimeError(
                    f"EC identity changed: 0x{identity[0]:04X}/0x{identity[1]:02X}"
                )
            if self.action == "connect":
                geometry = None
                if page_mode:
                    try:
                        geometry = ec.supported_geometry(identity)
                    except Exception as exc:
                        self.status.emit(f"Flash geometry unavailable: {exc}")
                try:
                    hold_active = bus.command("HOLDDBGR") == "HOLDDBGR ACTIVE"
                except TransportError:
                    hold_active = False
                self.finished.emit("connect", (identity, hold_active, geometry))
            elif self.action == "read":
                if not self.profile.read_protocol:
                    raise RuntimeError("Read is unavailable for this family")
                self.status.emit("Reading EC flash...")
                data = ec.read_flash(
                    READ_WINDOW,
                    lambda done, total: self.progress.emit(done * 100 // total),
                )
                self.finished.emit("read", (identity, data))
            elif self.action in ("write", "erase"):
                geometry = ec.supported_geometry(identity)
                if geometry != SUPPORTED_SIZE:
                    raise RuntimeError("Unsupported flash geometry")
                image = None
                if self.action == "write":
                    image = Path(self.image_path).read_bytes()
                    if len(image) != geometry:
                        raise RuntimeError(f"Image must be {geometry} bytes")
                    self.status.emit(f"Image SHA-256 {hashlib.sha256(image).hexdigest()}")
                self.status.emit("Erasing EC flash...")
                destructive_started = True
                erase_end = 40 if image is not None else 100
                ec.erase_flash(geometry, lambda done, total:
                               self.progress.emit(done * erase_end // total))
                if image is not None:
                    fast = getattr(bus, "fast_aai_available", lambda: False)()
                    self.status.emit("Programming EC flash (fast Pico path)..." if fast else
                                     "Programming EC flash (legacy USB path)...")
                    ec.write_flash(image, lambda done, total:
                                   self.progress.emit(40 + done * 40 // total))
                    self.status.emit("Verifying every byte...")
                    ec.verify_flash(image, lambda done, total:
                                    self.progress.emit(80 + done * 20 // total))
                self.finished.emit(self.action, identity)
        except Exception as exc:
            detail = f"{type(exc).__name__}: {exc}"
            if destructive_started:
                detail = ("Flash operation stopped after erase began. The EC may not boot. "
                          + detail)
            self.failed.emit(detail)
        finally:
            if bus:
                try:
                    bus.close()
                except Exception as exc:
                    self.failed.emit(f"USB release failed: {exc}")


class Window(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("EC Programmer")
        self.setStyleSheet(STYLESHEET)
        self.resize(1050, 1010)
        self.setMinimumSize(750, 560)
        self.thread = None
        self.pending_read = None
        self.pending_identity = None
        self.connected_identity = None
        self.connected_geometry = None
        self.keepalive = QTimer(self)
        self.keepalive.setInterval(5000)
        self.keepalive.timeout.connect(self.refresh_debug_hold)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.setCentralWidget(scroll)
        root = QWidget()
        root.setObjectName("root")
        scroll.setWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(24, 20, 24, 20)
        outer.setSpacing(13)
        title = QLabel("EC Programmer")
        title.setObjectName("title")
        outer.addWidget(title)
        subtitle = QLabel("Select the target, connect, then choose an operation")
        subtitle.setObjectName("subtitle")
        outer.addWidget(subtitle)

        connection = QGroupBox("Connection")
        connection_layout = QVBoxLayout(connection)
        connection_layout.setSpacing(11)
        outer.addWidget(connection)
        row = QHBoxLayout()
        row.setSpacing(10)
        connection_layout.addLayout(row)
        row.addWidget(QLabel("Pico / COM"))
        self.port = QComboBox()
        self.port.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        row.addWidget(self.port, 1)
        self.refresh_button = QPushButton("Refresh")
        self.refresh_button.setObjectName("quiet")
        self.refresh_button.clicked.connect(self.refresh)
        row.addWidget(self.refresh_button)

        target = QGroupBox("Target EC")
        target_layout = QVBoxLayout(target)
        target_layout.setSpacing(11)
        outer.addWidget(target)
        row = QHBoxLayout()
        row.setSpacing(10)
        target_layout.addLayout(row)
        row.addWidget(QLabel("Manufacturer"))
        self.manufacturer = QComboBox()
        self.manufacturer.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.manufacturer.addItems(FAMILIES_BY_MANUFACTURER)
        row.addWidget(self.manufacturer, 1)
        row.addWidget(QLabel("Model / family"))
        self.model = QComboBox()
        self.model.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        for profile in FAMILIES_BY_MANUFACTURER["ITE"]:
            self.model.addItem(profile.name, profile)
        row.addWidget(self.model, 2)
        row.addWidget(QLabel("SDA"))
        self.sda = QSpinBox()
        self.sda.setRange(0, 28)
        self.sda.setValue(7)
        self.sda.setToolTip("Pico GPIO connected to EC SDA")
        row.addWidget(self.sda)
        row.addWidget(QLabel("SCL"))
        self.scl = QSpinBox()
        self.scl.setRange(0, 28)
        self.scl.setValue(6)
        self.scl.setToolTip("Pico GPIO connected to EC SCL")
        row.addWidget(self.scl)
        for spin in (self.sda, self.scl):
            spin.lineEdit().setTextMargins(10, 0, 2, 0)
        row = QHBoxLayout()
        target_layout.addLayout(row)
        row.addStretch(1)
        self.detect = QPushButton("Connect to EC")
        self.detect.setObjectName("primary")
        self.detect.clicked.connect(lambda: self.start("connect"))
        row.addWidget(self.detect)
        row.addStretch(1)

        self.identity = QLabel("EC: not connected | Flash: not identified")
        self.identity.setWordWrap(True)
        self.identity.setObjectName("identity")
        target_layout.addWidget(self.identity)

        operations = QGroupBox("Operations")
        operations_layout = QVBoxLayout(operations)
        operations_layout.setSpacing(10)
        outer.addWidget(operations)
        row = QHBoxLayout()
        row.setSpacing(10)
        operations_layout.addLayout(row)
        self.read = QPushButton("Read")
        self.read.setObjectName("primary")
        self.read.clicked.connect(lambda: self.start("read"))
        row.addWidget(self.read, 1)
        self.write = QPushButton("Write (Erase + Write)")
        self.write.clicked.connect(lambda: self.start("write"))
        row.addWidget(self.write, 1)
        self.erase = QPushButton("Erase")
        self.erase.clicked.connect(lambda: self.start("erase"))
        row.addWidget(self.erase, 1)
        operation_hint = QLabel("Read saves a backup. Write verifies the programmed image.")
        operation_hint.setObjectName("hint")
        operation_hint.setWordWrap(True)
        operations_layout.addWidget(operation_hint)
        self.progress = QProgressBar()
        operations_layout.addWidget(self.progress)
        self.status = QLabel("Ready")
        self.status.setWordWrap(True)
        self.status.setObjectName("status")
        operations_layout.addWidget(self.status)

        journal = QGroupBox("Log")
        journal_layout = QVBoxLayout(journal)
        journal_layout.setSpacing(9)
        outer.addWidget(journal, 1)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        journal_layout.addWidget(self.log, 1)
        row = QHBoxLayout()
        journal_layout.addLayout(row)
        row.addStretch(1)
        save_log = QPushButton("Save log")
        save_log.setObjectName("quiet")
        save_log.clicked.connect(self.save_log)
        row.addWidget(save_log)

        credit = QLabel("Software by R89 Repairs | www.r89-repairs.ro")
        credit.setObjectName("credit")
        credit.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.statusBar().setSizeGripEnabled(False)
        self.statusBar().addPermanentWidget(credit, 1)

        self.port.currentIndexChanged.connect(self.reset_identity)
        self.manufacturer.currentIndexChanged.connect(self.on_manufacturer_changed)
        self.model.currentIndexChanged.connect(self.on_model_changed)
        self.sda.valueChanged.connect(self.reset_identity)
        self.scl.valueChanged.connect(self.reset_identity)
        self.refresh()
        i = self.model.findText("IT8xxx")
        self.model.setCurrentIndex(i)
        self.on_model_changed()
        self.note("Select a family and connect to the EC.")

    def note(self, message):
        self.log.appendPlainText(f"{datetime.now():%Y-%m-%d %H:%M:%S}  {message}")
        self.status.setText(message)

    def refresh(self):
        old = self.port.currentData()
        self.port.blockSignals(True)
        self.port.clear()
        for device, description in ports():
            self.port.addItem(f"{device} — {description}", device)
        if old:
            i = self.port.findData(old)
            if i >= 0:
                self.port.setCurrentIndex(i)
        self.port.blockSignals(False)
        self.reset_identity()

    def update_buttons(self):
        idle = self.thread is None
        config_enabled = idle and self.pending_read is None
        port_selected = self.port.currentData() is not None
        profile = self.model.currentData()
        for control in (self.port, self.refresh_button, self.manufacturer,
                        self.model, self.sda, self.scl):
            control.setEnabled(config_enabled)
        self.detect.setEnabled(config_enabled and port_selected and profile is not None)
        self.read.setText("Save read…" if self.pending_read is not None else "Read")
        self.read.setEnabled(idle and (self.pending_read is not None or
                             (port_selected and profile is not None and
                              profile.read_protocol and self.connected_identity is not None)))
        destructive_ready = (idle and self.pending_read is None and port_selected and
                             profile is not None and profile.read_protocol and
                             self.connected_identity is not None and
                             self.connected_geometry == SUPPORTED_SIZE)
        self.write.setEnabled(destructive_ready)
        self.erase.setEnabled(destructive_ready)

    def reset_identity(self):
        self.keepalive.stop()
        self.connected_identity = None
        self.connected_geometry = None
        self.identity.setText("EC: not connected | Flash: not identified")
        self.update_buttons()

    def on_model_changed(self):
        self.reset_identity()

    def on_manufacturer_changed(self):
        families = FAMILIES_BY_MANUFACTURER.get(self.manufacturer.currentText(), ())
        self.model.blockSignals(True)
        self.model.clear()
        for profile in families:
            self.model.addItem(profile.name, profile)
        self.model.blockSignals(False)
        self.on_model_changed()

    def start(self, action):
        if self.thread is not None:
            return
        if action == "read" and self.pending_read is not None:
            self.save_read()
            return
        profile = self.model.currentData()
        if not profile or not self.port.currentData():
            return
        if action in ("read", "write", "erase") and self.connected_identity is None:
            return
        image_path = None
        if action in ("write", "erase"):
            if self.connected_geometry != SUPPORTED_SIZE:
                return
            if action == "write":
                image_path, _ = QFileDialog.getOpenFileName(
                    self, "Select EC firmware image", str(Path.home()),
                    "Binary image (*.bin);;All files (*)"
                )
                if not image_path:
                    return
                try:
                    image_size = Path(image_path).stat().st_size
                except OSError as exc:
                    QMessageBox.critical(self, "Cannot open image", str(exc))
                    return
                if image_size != self.connected_geometry:
                    QMessageBox.critical(self, "Wrong image size",
                                         f"Expected {self.connected_geometry} bytes; file has {image_size}.")
                    return
            label = "erase and write" if action == "write" else "erase"
            message = (f"This will {label} the EC flash. "
                       + ("The written image will be verified. " if action == "write" else "")
                       + "Continue?")
            if QMessageBox.question(self, "Confirm EC flash operation", message,
                                    QMessageBox.StandardButton.Yes |
                                    QMessageBox.StandardButton.No,
                                    QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
                return
        self.progress.setValue(0)
        self.note("Connecting to EC..." if action == "connect" else
                  "Checking the EC debug session...")
        self.thread = QThread()
        self.worker = Worker(action, self.port.currentData(),
                             (self.sda.value(), self.scl.value()), profile,
                             self.connected_identity, image_path)
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.progress.connect(self.progress.setValue)
        self.worker.status.connect(self.note)
        self.worker.power_cycle_needed.connect(self.show_power_cycle_prompt)
        self.worker.finished.connect(self.on_finished)
        self.worker.failed.connect(self.on_failed)
        self.worker.finished.connect(self.thread.quit)
        self.worker.failed.connect(self.thread.quit)
        self.thread.finished.connect(self.worker.deleteLater)
        self.thread.finished.connect(self.on_thread_finished)
        self.update_buttons()
        self.thread.start()

    def show_power_cycle_prompt(self):
        continuation = ("Connection will continue automatically." if
                        self.worker.action == "connect" else
                        "The operation will start automatically.")
        QMessageBox.information(
            self,
            "Power cycle the EC",
            "Pico is ready. If the laptop adapter is plugged in, unplug it for "
            "5 seconds, then reconnect it. If it is already unplugged, connect it now. "
            "Keep Pico and the EC wires connected. "
            + continuation,
        )

    def on_finished(self, action, result):
        if action == "connect":
            (chip, version), hold_active, geometry = result
            if self.model.currentData().read_protocol and (chip & 0xF000) != 0x8000:
                self.note(f"Identified 0x{chip:04X}/0x{version:02X}, outside the selected IT8xxx family.")
                self.reset_identity()
                return
            self.connected_identity = (chip, version)
            self.connected_geometry = geometry
            self.identity.setText(
                f"CHIPID 0x{chip:04X} | CHIPVER 0x{version:02X} | "
                f"Flash {'256 KiB' if geometry == SUPPORTED_SIZE else 'capacity unknown'}"
            )
            if geometry == SUPPORTED_SIZE:
                self.note("EC connected. Read, Write and Erase are available.")
            elif self.model.currentData().read_protocol:
                self.note("EC connected. Read is available; flash geometry is unverified.")
            else:
                self.note("EC identified. Read protocol for this family is not implemented yet.")
            if hold_active and self.model.currentData().read_protocol:
                self.keepalive.start()
            self.update_buttons()
        elif action == "read":
            identity, data = result
            chip, version = identity
            self.identity.setText(
                f"CHIPID 0x{chip:04X} | CHIPVER 0x{version:02X} | "
                f"Read {len(data) // 1024} KiB"
            )
            self.pending_read = data
            self.pending_identity = identity
            self.note(f"Read complete: {len(data)} bytes. Choose where to save the backup.")
            self.save_read()
        elif action in ("write", "erase"):
            self.note("Write complete and verified." if action == "write" else "Erase complete.")
            self.connected_identity = result
            self.update_buttons()

    def save_read(self):
        if self.pending_read is None:
            return
        chip = self.pending_identity[0] if self.pending_identity else 0
        suggested = Path.home() / f"ITE-{chip:04X}-{datetime.now():%Y%m%d-%H%M%S}.bin"
        path, _ = QFileDialog.getSaveFileName(
            self, "Save EC backup", str(suggested), "Binary image (*.bin);;All files (*)"
        )
        if not path:
            self.note("Read is held in memory. Press Read again to choose a save location.")
            return
        try:
            digest = save_new(path, self.pending_read)
        except Exception as exc:
            QMessageBox.critical(self, "Backup not saved", str(exc))
            self.note("Backup is still in memory. Press Read to choose another location.")
            return
        self.pending_read = None
        self.pending_identity = None
        self.note(f"Saved {path} | SHA-256 {digest}")
        self.update_buttons()

    def on_failed(self, message):
        self.note("ERROR: " + message)
        if self.worker.action in ("write", "erase"):
            QMessageBox.critical(self, "EC flash operation stopped", message)

    def refresh_debug_hold(self):
        if self.thread is not None or self.connected_identity is None:
            return
        try:
            with PicoTransport(self.port.currentData(), timeout=2) as bus:
                bus.pins(self.sda.value(), self.scl.value())
                if bus.command("HOLDDBGR") != "HOLDDBGR ACTIVE":
                    raise TransportError("EC debug hold expired")
                bus.read_page(0)
        except Exception as exc:
            self.note(f"EC connection lost: {exc}")
            self.reset_identity()

    def on_thread_finished(self):
        self.thread.deleteLater()
        self.thread = None
        self.update_buttons()

    def save_log(self):
        path, _ = QFileDialog.getSaveFileName(self, "Save log", "pico-ec-log.txt", "Text (*.txt)")
        if path:
            try:
                with open(path, "x", encoding="utf-8") as file:
                    file.write(self.log.toPlainText() + "\n")
            except Exception as exc:
                QMessageBox.critical(self, "Error", str(exc))

    def closeEvent(self, event):
        if self.thread is not None:
            QMessageBox.information(self, "Operation in progress", "Wait for it to finish.")
            event.ignore()
        elif self.pending_read is not None:
            answer = QMessageBox.question(
                self, "Unsaved backup", "The read is not saved. Close and discard it?"
            )
            if answer != QMessageBox.StandardButton.Yes:
                event.ignore()
            else:
                event.accept()
        else:
            self.keepalive.stop()
            event.accept()


def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    window = Window()
    window.show()
    return app.exec()
