# SPDX-FileCopyrightText: 2026 R89 Repairs and contributors
# SPDX-License-Identifier: GPL-2.0-or-later

"""EC connection and recovery, independent of Qt widgets."""
import time
from .transport import TransportError


def validate_ite_pins(sda, scl):
    valid = lambda pin: 0 <= pin <= 22 or 26 <= pin <= 28
    if not valid(sda) or not valid(scl) or abs(sda - scl) != 1:
        raise ValueError("ITE requires two consecutive GPIOs from 0-22 or 26-28 (for example SDA=7, SCL=6).")


class DeviceSession:
    def __init__(self, port, pins, profile, bus_factory, ite_factory, ene_factory,
                 status, power_cycle_needed):
        self.port, self.pins, self.profile = port, pins, profile
        self.bus_factory, self.ite_factory, self.ene_factory = bus_factory, ite_factory, ene_factory
        self.status, self.power_cycle_needed = status, power_cycle_needed
        self.bus = self.ec = None
        self.ene = getattr(profile, "transport", "ite") == "ene_edi"

    @staticmethod
    def unavailable(exc):
        return any(code in str(exc) for code in ("ADDRESS_NACK", "DATA_NACK", "SCL_LOW_TIMEOUT"))

    def _open(self):
        self.bus = self.bus_factory(self.port, timeout=5)
        if hasattr(self.bus, "capabilities"):
            self.bus.capabilities()
        if self.ene:
            self.ec = self.ene_factory(self.bus)
        else:
            validate_ite_pins(*self.pins)
            self.bus.pins(*self.pins)
            if hasattr(self.bus, "supports") and self.bus.supports("I2CTIMING"):
                if self.bus.command("I2CTIMING 5") != "OK":
                    raise TransportError("Cannot select the validated I2C timing")
            self.ec = self.ite_factory(self.bus, page_mode=self.profile.read_protocol)

    def _power_status(self, message):
        self.status(message)
        if message.startswith("Pico is armed:"):
            self.power_cycle_needed()

    def connect(self, action):
        self._open()
        if self.ene or not self.profile.read_protocol:
            return self.ec.enter_and_identify()
        try:
            identity = self.ec.identify()
            if action != "connect":
                self.status("EC debug session is active; continuing without a power cycle.")
            return identity
        except TransportError as exc:
            if not self.unavailable(exc):
                raise
        try:
            return self.ec.enter_and_identify()
        except TransportError as exc:
            if "ENTERDBGR_NO_ACK" not in str(exc):
                raise
        self.close()
        self.status("EC debug entry needs a target reset.")
        self.bus_factory.wait_power_cycle(self.port, self.pins, self._power_status)
        self._open()
        last_error = None
        for delay in (0, 0.5, 1, 2, 3, 4):
            if delay:
                time.sleep(delay)
            try:
                return self.ec.identify()
            except TransportError as exc:
                if not self.unavailable(exc):
                    raise
            try:
                return self.ec.enter_and_identify()
            except TransportError as exc:
                if "ENTERDBGR_NO_ACK" not in str(exc):
                    raise
                last_error = exc
                self.status("EC is powered but has not acknowledged DBGR; retrying...")
        raise last_error

    def refresh(self, expected_identity):
        self._open()
        if self.bus.command("HOLDDBGR") != "HOLDDBGR ACTIVE":
            raise TransportError("EC debug hold expired")
        identity = self.ec.identify()
        if identity != expected_identity:
            raise TransportError("EC identity changed during keepalive")
        if not (hasattr(self.bus, "supports") and self.bus.supports("SESSION")):
            self.bus.read_page(0)
        return identity

    def prepare_destructive(self):
        if self.ene or not hasattr(self.bus, "capabilities"):
            return
        caps = self.bus.capabilities()
        if caps.intersection({"AAI64", "AAIV2_64", "PAGE64", "ERASESECTOR"}):
            if self.bus.command("HOLDDBGR") != "HOLDDBGR ACTIVE":
                # The old page command renews the watchdog session. This is
                # a control read, not an automatic backup or erase check.
                self.bus.read_page(0)
                if self.bus.command("HOLDDBGR") != "HOLDDBGR ACTIVE":
                    raise TransportError("No active debug hold; reconnect before erasing")

    def close(self):
        bus, self.bus = self.bus, None
        if bus is not None:
            bus.close()

    def disconnect(self):
        self.bus = self.bus_factory(self.port, timeout=5)
        if hasattr(self.bus, "supports") and self.bus.supports("SESSION"):
            if self.bus.command("ENDSESSION") != "OK":
                raise TransportError("Session end was not acknowledged")
