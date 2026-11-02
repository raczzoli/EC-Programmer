# SPDX-FileCopyrightText: 2026 R89 Repairs and contributors
# SPDX-License-Identifier: GPL-2.0-or-later

"""Windows GUI for ITE and ENE EC flash operations."""

import sys
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QThread, QTimer, Qt
from PySide6.QtWidgets import (
    QApplication, QComboBox, QFileDialog, QFrame, QGroupBox, QHBoxLayout,
    QLabel, QMainWindow, QMessageBox, QPlainTextEdit, QProgressBar, QPushButton,
    QScrollArea, QSizePolicy, QSpinBox, QVBoxLayout, QWidget,
)

from .ec import FLASH_SIZES, save_new
from .ene import FLASH_SIZE as ENE_FLASH_SIZE
from .models import FAMILIES_BY_MANUFACTURER
from .style import STYLESHEET
from .transport import ports

from .operations import Worker, READ_SIZES, resolve_read_size
from .session import validate_ite_pins
from .version import VERSION, BUILD_ID


class Window(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"EC Programmer {VERSION}")
        self.setStyleSheet(STYLESHEET)
        self.resize(1050, 1010)
        self.setMinimumSize(1050, 560)
        available = self.screen().availableGeometry()
        self.resize(1050, max(560, min(1010, available.height() - 60)))
        self.thread = None
        self._close_when_idle = False
        self._shutdown_complete = False
        self._pending_operation = None
        self.power_prompt = None
        self.pending_read = None
        self.pending_identity = None
        self.connected_identity = None
        self.connected_protocol = None
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
        outer.setSpacing(11)
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
        self.manufacturer.setMinimumWidth(85)
        self.manufacturer.addItems(FAMILIES_BY_MANUFACTURER)
        row.addWidget(self.manufacturer, 1)
        row.addWidget(QLabel("Model"))
        self.model = QComboBox()
        self.model.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.model.setMinimumWidth(115)
        for profile in FAMILIES_BY_MANUFACTURER["ITE"]:
            self.model.addItem(profile.name, profile)
        row.addWidget(self.model, 2)
        self.sda_label = QLabel("SDA")
        row.addWidget(self.sda_label)
        self.sda = QSpinBox()
        self.sda.setFixedWidth(82)
        self.sda.setRange(0, 28)
        self.sda.setValue(7)
        self.sda.setToolTip("Pico GPIO connected to EC SDA")
        row.addWidget(self.sda)
        self.scl_label = QLabel("SCL")
        row.addWidget(self.scl_label)
        self.scl = QSpinBox()
        self.scl.setFixedWidth(82)
        self.scl.setRange(0, 28)
        self.scl.setValue(6)
        self.scl.setToolTip("Pico GPIO connected to EC SCL")
        row.addWidget(self.scl)
        for spin in (self.sda, self.scl):
            spin.lineEdit().setTextMargins(10, 0, 2, 0)
        self.ene_wiring = QLabel("EDI: GP4=DO, GP5=CS, GP6=CLK, GP7=DI; KSO3=GND")
        self.ene_wiring.setToolTip(
            "EC KSI7 -> GP4, KSI4 -> GP5, KSI5 -> GP6, KSI6 -> GP7; "
            "KSO3 -> GND and a common Pico/board ground. Power the EC from its board."
        )
        self.ene_wiring.hide()
        row.addWidget(self.ene_wiring)
        row.addWidget(QLabel("Size"))
        self.flash_size = QComboBox()
        self.flash_size.setFixedWidth(130)
        self.flash_size.setToolTip(
            "Select the EC flash size. Read, Write and Erase use this size; "
            "Write and Erase also require a recognized flash protocol."
        )
        self.flash_size.addItem("Select size", None)
        for size in READ_SIZES:
            self.flash_size.addItem(f"{size // 1024} KiB", size)
        row.addWidget(self.flash_size)
        row = QHBoxLayout()
        target_layout.addLayout(row)
        row.addStretch(1)
        self.detect = QPushButton("Connect to EC")
        self.detect.setObjectName("primary")
        self.detect.clicked.connect(lambda: self.start("connect"))
        row.addWidget(self.detect)
        row.addStretch(1)

        self.identity = QLabel("EC: not connected | Flash size: not selected")
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
        operation_hint = QLabel(
            "Read starts at address 0 and uses the selected flash size. "
            "Write verifies the programmed image."
        )
        operation_hint.setObjectName("hint")
        operation_hint.setWordWrap(True)
        operations_layout.addWidget(operation_hint)
        self.progress = QProgressBar()
        self.progress.setFormat("%p%")
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
        self.flash_size.currentIndexChanged.connect(self.on_flash_size_changed)
        self.refresh()
        i = self.model.findText("IT8xxx")
        self.model.setCurrentIndex(i)
        self.on_model_changed()
        self.note("Select a family and connect to the EC.")
        self.log.appendPlainText(f"Application {VERSION} | Build {BUILD_ID}")

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
                        self.model, self.sda, self.scl, self.flash_size):
            control.setEnabled(config_enabled)
        self.detect.setEnabled(config_enabled and port_selected and profile is not None)
        self.read.setText("Save read…" if self.pending_read is not None else "Read")
        self.read.setEnabled(idle and (self.pending_read is not None or
                             (port_selected and profile is not None and
                              profile.read_protocol and self.connected_identity is not None and
                              self.flash_size.currentData() in READ_SIZES)))
        destructive_ready = (idle and self.pending_read is None and port_selected and
                             profile is not None and profile.read_protocol and
                             self.connected_identity is not None and
                             self.connected_protocol is not None and
                             self.flash_size.currentData() in FLASH_SIZES)
        self.write.setEnabled(destructive_ready)
        self.erase.setEnabled(destructive_ready)

    def reset_identity(self):
        self.keepalive.stop()
        self.connected_identity = None
        self.connected_protocol = None
        self.update_identity_label()
        self.update_buttons()

    def update_identity_label(self):
        size = self.flash_size.currentData()
        selected = f"{size // 1024} KiB selected" if size else "not selected"
        if self.connected_identity is None:
            self.identity.setText(f"EC: not connected | Flash size: {selected}")
            return
        chip, version = self.connected_identity
        protocol = (f"{self.connected_protocol.name} "
                    f"({self.connected_protocol.program_method})"
                    if self.connected_protocol else "unavailable")
        if self.manufacturer.currentText() == "ENE":
            self.identity.setText(
                f"ENE KB9052 | HWVERSION 0x{chip:02X} | EDIID 0x{version:02X} | "
                f"Flash size: {selected} | Flash protocol: {protocol}"
            )
        else:
            self.identity.setText(
                f"CHIPID 0x{chip:04X} | CHIPVER 0x{version:02X} | "
                f"Flash size: {selected} | Flash protocol: {protocol}"
            )

    def on_flash_size_changed(self):
        self.update_identity_label()
        self.update_buttons()

    def on_model_changed(self):
        self.reset_identity()

    def on_manufacturer_changed(self):
        families = FAMILIES_BY_MANUFACTURER.get(self.manufacturer.currentText(), ())
        ene = self.manufacturer.currentText() == "ENE"
        for widget in (self.sda_label, self.sda, self.scl_label, self.scl):
            widget.setVisible(not ene)
        self.ene_wiring.setVisible(ene)
        for index in range(1, self.flash_size.count()):
            item = self.flash_size.model().item(index)
            if item is not None:
                item.setEnabled(not ene or self.flash_size.itemData(index) == ENE_FLASH_SIZE)
        if ene:
            self.flash_size.setCurrentIndex(self.flash_size.findData(ENE_FLASH_SIZE))
        self.model.blockSignals(True)
        self.model.clear()
        for profile in families:
            self.model.addItem(profile.name, profile)
        self.model.blockSignals(False)
        self.on_model_changed()

    def start(self, action, image_path=None, confirmed=False):
        if self.thread is not None:
            return
        if action == "read" and self.pending_read is not None:
            self.save_read()
            return
        profile = self.model.currentData()
        if not profile or not self.port.currentData():
            return
        if profile.transport == "ite":
            try:
                validate_ite_pins(self.sda.value(), self.scl.value())
            except ValueError as exc:
                QMessageBox.information(self, "Select GPIO pins", str(exc))
                return
        if action in ("read", "write", "erase") and self.connected_identity is None:
            return
        read_size = None
        if action == "read":
            try:
                read_size = resolve_read_size(self.flash_size.currentData())
            except ValueError as exc:
                QMessageBox.information(self, "Select flash size", str(exc))
                return
        if action in ("write", "erase"):
            if (self.connected_protocol is None or
                    self.flash_size.currentData() not in FLASH_SIZES):
                return
            if action == "write" and image_path is None:
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
                if image_size != self.flash_size.currentData():
                    QMessageBox.critical(self, "Wrong image size",
                                         f"Expected {self.flash_size.currentData()} bytes; file has {image_size}.")
                    return
            label = "erase and write" if action == "write" else "erase"
            message = (f"This will {label} the EC flash. "
                       + ("The written image will be verified. " if action == "write" else "")
                       + "Continue?")
            if not confirmed and QMessageBox.question(self, "Confirm EC flash operation", message,
                                    QMessageBox.StandardButton.Yes |
                                    QMessageBox.StandardButton.No,
                                    QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
                return
            # Native dialogs process Qt events. A keepalive may have acquired
            # USB while the user selected/confirmed the image. Queue behind it.
            if self.thread is not None:
                self._pending_operation = (action, image_path)
                return
            if self.connected_identity is None:
                return
        if action not in ("keepalive", "disconnect"):
            self.progress.setValue(0)
            self.note("Connecting to EC..." if action == "connect" else
                      ("Opening the ENE EDI session..." if profile.transport == "ene_edi"
                       else "Checking the EC debug session..."))
        self.thread = QThread()
        self.worker = Worker(action, self.port.currentData(),
                             (self.sda.value(), self.scl.value()), profile,
                             self.connected_identity, image_path,
                             self.flash_size.currentData())
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.progress.connect(self.progress.setValue)
        self.worker.status.connect(self.note)
        self.worker.power_cycle_needed.connect(self.show_power_cycle_prompt)
        self.worker.finished.connect(self.on_finished)
        self.worker.failed.connect(self.on_failed)
        self.worker.warning.connect(self.on_warning)
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
        self.power_prompt = QMessageBox(
            QMessageBox.Icon.Information,
            "Power cycle the EC",
            "Pico is ready. If the laptop adapter is plugged in, unplug it for "
            "5 seconds, then reconnect it. If it is already unplugged, connect it now. "
            "Keep Pico and the EC wires connected. "
            + continuation, QMessageBox.StandardButton.Ok, self,
        )
        self.power_prompt.show()

    def on_finished(self, action, result):
        if self.power_prompt is not None:
            self.power_prompt.close()
            self.power_prompt.deleteLater()
            self.power_prompt = None
        if action == "keepalive":
            return
        if action == "disconnect":
            self.reset_identity()
            return
        if action == "connect":
            (chip, version), hold_active, detected_protocol = result
            if self.manufacturer.currentText() == "ITE" and \
                    self.model.currentData().read_protocol and (chip & 0xF000) != 0x8000:
                self.note(f"Identified 0x{chip:04X}/0x{version:02X}, outside the selected IT8xxx family.")
                self.reset_identity()
                return
            self.connected_identity = (chip, version)
            self.connected_protocol = detected_protocol
            self.update_identity_label()
            if detected_protocol is not None and self.flash_size.currentData() in FLASH_SIZES:
                self.note("EC connected. Read, Write and Erase are available.")
            elif self.model.currentData().read_protocol:
                if self.flash_size.currentData() in READ_SIZES:
                    self.note("EC connected. Read is available for the selected size.")
                else:
                    self.note("EC connected. Select a flash size to enable Read.")
            else:
                self.note("EC identified. Read protocol for this family is not implemented yet.")
            if hold_active and self.model.currentData().read_protocol:
                self.keepalive.start()
            self.update_buttons()
        elif action == "read":
            identity, data = result
            self.update_identity_label()
            self.pending_read = data
            self.pending_identity = identity
            self.note(f"Read complete: {len(data)} bytes (selected size). Choose where to save.")
            self.save_read()
        elif action in ("write", "erase"):
            self.note("Write complete and verified." if action == "write" else "Erase complete.")
            self.connected_identity = result
            self.update_buttons()

    def save_read(self):
        if self.pending_read is None:
            return
        chip = self.pending_identity[0] if self.pending_identity else 0
        prefix = (f"ENE-KB9052-HW{chip:02X}" if self.manufacturer.currentText() == "ENE"
                  else f"ITE-{chip:04X}")
        suggested = Path.home() / (
            f"{prefix}-{len(self.pending_read) // 1024}KiB-"
            f"{datetime.now():%Y%m%d-%H%M%S}.bin"
        )
        path, _ = QFileDialog.getSaveFileName(
            self, "Save EC read", str(suggested), "Binary image (*.bin);;All files (*)"
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
        if self.power_prompt is not None:
            self.power_prompt.close()
            self.power_prompt.deleteLater()
            self.power_prompt = None
        self.note("ERROR: " + message)
        self.reset_identity()
        if self.worker.action in ("write", "erase"):
            QMessageBox.critical(self, "EC flash operation stopped", message)

    def on_warning(self, message):
        self.note("WARNING: " + message)
        self.reset_identity()

    def refresh_debug_hold(self):
        if (self.thread is not None or self.connected_identity is None or
                self.manufacturer.currentText() == "ENE"):
            return
        self.start("keepalive")

    def on_thread_finished(self):
        self.thread.deleteLater()
        self.thread = None
        self.update_buttons()
        if self._close_when_idle:
            self._pending_operation = None
            self.close()
        elif self._pending_operation is not None:
            action, image_path = self._pending_operation
            self._pending_operation = None
            self.start(action, image_path, confirmed=True)

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
            if self.worker.action in ("keepalive", "disconnect"):
                self._close_when_idle = True
                self.keepalive.stop()
            else:
                QMessageBox.information(self, "Operation in progress", "Wait for it to finish.")
            event.ignore()
        elif self.pending_read is not None:
            answer = QMessageBox.question(
                self, "Unsaved backup", "The read is not saved. Close and discard it?"
            )
            if answer != QMessageBox.StandardButton.Yes:
                event.ignore()
            else:
                self.pending_read = None
                self.pending_identity = None
                self.closeEvent(event)
        else:
            self.keepalive.stop()
            if self.connected_identity is not None and not self._shutdown_complete:
                self._shutdown_complete = True
                self._close_when_idle = True
                self.start("disconnect")
                event.ignore()
            else:
                event.accept()


def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    window = Window()
    window.show()
    if "--smoke-test" in sys.argv:
        # Build-time startup check; only enumerates ports, never opens them.
        QTimer.singleShot(300, window.close)
    return app.exec()
