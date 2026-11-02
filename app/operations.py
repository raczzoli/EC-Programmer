# SPDX-FileCopyrightText: 2026 R89 Repairs and contributors
# SPDX-License-Identifier: GPL-2.0-or-later

"""Operation orchestration. One worker owns USB until cleanup is complete."""
import hashlib
import time
from pathlib import Path
from PySide6.QtCore import QObject, Signal, Slot
from .ec import ECProbe, FLASH_SIZES
from .ene import EneEC
from .session import DeviceSession
from .transport import PicoTransport, TransportError

READ_SIZES = FLASH_SIZES


def resolve_read_size(size):
    if size not in READ_SIZES:
        raise ValueError("Select a flash size before reading.")
    return size


class Worker(QObject):
    progress = Signal(int)
    status = Signal(str)
    warning = Signal(str)
    power_cycle_needed = Signal()
    finished = Signal(str, object)
    failed = Signal(str)

    def __init__(self, action, port, pins, profile, expected_identity=None,
                 image_path=None, read_size=None):
        super().__init__()
        self.action, self.port, self.pins, self.profile = action, port, pins, profile
        self.expected_identity, self.image_path, self.read_size = expected_identity, image_path, read_size

    def programming_label(self, bus, protocol, ene):
        if ene:
            return "Programming ENE flash through EDI..."
        methods = {
            "aai_legacy": ("fast_aai256_available", "fast_aai_available", "AAI"),
            "aai_v2": ("fast_aai_v2_256_available", "fast_aai_v2_available", "AAI v2"),
            "page_program": (None, "fast_page_available", "page program"),
        }
        if protocol.program_method not in methods:
            raise RuntimeError("Unsupported programming method")
        large, small, name = methods[protocol.program_method]
        if large and getattr(bus, large, lambda: False)():
            return f"Programming EC flash ({name}, 256-byte Pico blocks)..."
        if getattr(bus, small, lambda: False)():
            return f"Programming EC flash ({name}, 64-byte Pico blocks)..."
        return f"Programming EC flash ({protocol.name}, {protocol.program_method}, USB fallback)..."

    def stage(self, name, operation):
        started = time.monotonic()
        result = operation()
        self.status.emit(f"{name} finished in {time.monotonic()-started:.1f} s.")
        return result

    @Slot()
    def run(self):
        session = DeviceSession(self.port, self.pins, self.profile, PicoTransport,
                                ECProbe, EneEC, self.status.emit, self.power_cycle_needed.emit)
        destructive_started = False
        result = error = cleanup_error = None
        try:
            if self.action == "keepalive":
                result = session.refresh(self.expected_identity)
            elif self.action == "disconnect":
                session.disconnect()
            else:
                image = None
                if self.action in ("read", "write", "erase"):
                    resolve_read_size(self.read_size)
                if self.action == "write":
                    image = Path(self.image_path).read_bytes()
                    if len(image) != self.read_size:
                        raise RuntimeError(f"Image must be {self.read_size} bytes")
                identity = session.connect(self.action)
                bus, ec = session.bus, session.ec
                if self.action != "connect" and identity != self.expected_identity:
                    raise RuntimeError(f"EC identity changed: 0x{identity[0]:04X}/0x{identity[1]:02X}")
                if self.action == "connect":
                    if hasattr(bus, "firmware_info"):
                        self.status.emit(bus.firmware_info())
                    protocol = None
                    if self.profile.read_protocol:
                        try:
                            protocol = ec.flash_protocol(identity)
                        except TransportError:
                            raise
                        except Exception as exc:
                            self.status.emit(f"Flash protocol unavailable: {exc}")
                    hold_active = False
                    if not session.ene:
                        try:
                            hold_active = bus.command("HOLDDBGR") == "HOLDDBGR ACTIVE"
                        except TransportError as exc:
                            if str(exc) != "ERR COMMAND":
                                raise
                    result = identity, hold_active, protocol
                elif self.action == "read":
                    if not self.profile.read_protocol:
                        raise RuntimeError("Read is unavailable for this family")
                    self.status.emit(f"Reading {self.read_size // 1024} KiB from address 0...")
                    data = self.stage("Read", lambda: ec.read_flash(
                        self.read_size, lambda done,total: self.progress.emit(done*100//total)))
                    result = identity, data
                elif self.action in ("write", "erase"):
                    if not self.profile.read_protocol:
                        raise RuntimeError("Flash operations are unavailable for this family")
                    protocol = ec.flash_protocol(identity)
                    # Finish all preparation before the first erase command.
                    label = self.programming_label(bus, protocol, session.ene) if image is not None else None
                    session.prepare_destructive()
                    if image is not None:
                        self.status.emit(f"Image SHA-256 {hashlib.sha256(image).hexdigest()}")
                    self.status.emit("Erasing EC flash...")
                    destructive_started = True
                    erase_end = 40 if image is not None else 100
                    self.stage("Erase", lambda: ec.erase_flash(self.read_size, protocol,
                        lambda done,total: self.progress.emit(done*erase_end//total)))
                    if image is not None:
                        self.status.emit(label)
                        self.stage("Programming", lambda: ec.write_flash(image, protocol,
                            lambda done,total: self.progress.emit(40+done*40//total)))
                        self.status.emit("Verifying every byte...")
                        self.stage("Verification", lambda: ec.verify_flash(image,
                            lambda done,total: self.progress.emit(80+done*20//total)))
                    result = identity
                else:
                    raise ValueError(f"Unknown action: {self.action}")
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            if destructive_started:
                error = "Flash operation stopped after erase began. The EC may not boot. " + error
        finally:
            try:
                session.close()
            except Exception as exc:
                cleanup_error = f"EC session cleanup failed: {exc}. Reconnect before another operation."
        # Exactly one terminal signal, and only after the USB owner is done.
        if error is not None:
            self.failed.emit(error)
        else:
            self.finished.emit(self.action, result)
        if cleanup_error:
            self.warning.emit(cleanup_error)
