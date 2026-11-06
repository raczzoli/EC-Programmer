# SPDX-FileCopyrightText: 2026 R89 Repairs and contributors
# SPDX-License-Identifier: GPL-2.0-or-later

"""Compact top-view LQFP drawing driven by the documented ENE catalog."""
from PySide6.QtCore import Qt, QRectF, QSize
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QWidget, QSizePolicy


class WiringDiagram(QWidget):
    COLORS = ("#38bdf8", "#a78bfa", "#fbbf24", "#34d399")

    def __init__(self, parent=None):
        super().__init__(parent)
        self.model = None
        self.setFixedHeight(225)
        self.setMinimumWidth(760)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def sizeHint(self):
        return QSize(850, 225)

    def set_model(self, model):
        self.model = model
        self.setVisible(model is not None)
        self.setAccessibleName(model.wiring if model else "EC wiring diagram")
        self.update()

    @staticmethod
    def pin_rect(pin):
        # Pin 1 at upper left; counterclockwise numbering viewed from above.
        x, y, pitch = 240, 34, 4
        i = (pin - 1) % 32
        side = (pin - 1) // 32
        if side == 0:
            return QRectF(x - 10, y + 9 + i*pitch, 10, 2.5)
        if side == 1:
            return QRectF(x + 9 + i*pitch, y + 146, 2.5, 10)
        if side == 2:
            return QRectF(x + 146, y + 9 + (31-i)*pitch, 10, 2.5)
        return QRectF(x + 9 + (31-i)*pitch, y - 10, 2.5, 10)

    def paintEvent(self, event):
        if self.model is None:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        scale = min(1.0, self.width()/850)
        p.translate((self.width()-850*scale)/2, 0)
        p.scale(scale, scale)
        font = QFont("Segoe UI")
        font.setPixelSize(13)
        p.setFont(font)

        def text(x, y, width, height, value, color="#cbd5e1", align=Qt.AlignmentFlag.AlignLeft):
            p.setPen(QColor(color))
            p.drawText(QRectF(x,y,width,height), align | Qt.AlignmentFlag.AlignVCenter, value)

        colors = {pin: self.COLORS[i] for i, (_, pin) in enumerate(self.model.pins)}
        colors[self.model.strap] = "#f87171"
        for pin in range(1,129):
            p.fillRect(self.pin_rect(pin), QColor(colors.get(pin, "#52657e")))
        p.setPen(QPen(QColor("#71849d"),1))
        p.setBrush(QColor("#0d1728"))
        p.drawRoundedRect(QRectF(240,34,146,146),7,7)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#f8fafc"))
        p.drawEllipse(QRectF(250,44,7,7))
        text(240,77,146,25,self.model.name,"#f8fafc",Qt.AlignmentFlag.AlignCenter)
        text(240,103,146,22,self.model.package,align=Qt.AlignmentFlag.AlignCenter)
        text(240,126,146,22,"TOP VIEW", "#94a3b8",Qt.AlignmentFlag.AlignCenter)
        text(173,31,53,22,"1  >", "#f8fafc",Qt.AlignmentFlag.AlignRight)
        text(203,155,25,22,"32",align=Qt.AlignmentFlag.AlignRight)
        text(236,193,28,19,"33")
        text(402,193,28,19,"64")
        text(399,155,28,22,"65")
        text(399,31,28,22,"96")
        text(367,2,28,19,"97")
        text(236,2,30,19,"128")
        # Brackets identify the two programming areas without obscuring pins.
        for first,last,label,color in ((self.model.strap,self.model.strap,"42", "#f87171"),
                                       (min(colors.keys() - {self.model.strap}), max(colors.keys() - {self.model.strap}), f"{min(pin for _, pin in self.model.pins)}-{max(pin for _, pin in self.model.pins)}", "#e2e8f0")):
            a,b=self.pin_rect(first),self.pin_rect(last)
            p.setPen(QPen(QColor(color),1))
            p.drawLine(a.center().x(),191,b.center().x(),191)
            p.drawLine(a.center().x(),187,a.center().x(),191)
            p.drawLine(b.center().x(),187,b.center().x(),191)
            text(a.center().x()-14,194,b.center().x()-a.center().x()+30,20,label,color,Qt.AlignmentFlag.AlignCenter)

        text(475,4,145,22,"EC pin", "#94a3b8")
        text(630,4,170,22,"Connect to", "#94a3b8")
        for i,(gpio,pin) in enumerate(self.model.pins):
            y=30+i*27
            p.fillRect(QRectF(459,y+6,4,13),QColor(self.COLORS[i]))
            text(475,y,145,24,str(pin),self.COLORS[i])
            text(630,y,170,24,f"Pico GP{gpio}",self.COLORS[i])
        text(475,138,145,24,f"{self.model.strap} (KSO3)","#f87171")
        text(630,138,170,24,"Board GND","#f87171")
        text(475,166,325,23,"Pico GND = Board GND")
        text(475,193,355,22,f"Ground pin {self.model.strap} before powering the EC.","#94a3b8")
        text(16,75,185,24,"Locate the pin-1 dot.")
        text(16,100,185,24,"Count counterclockwise.")
        text(16,125,185,24,"EC pins, not connector pins.")
        p.end()
