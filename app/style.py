"""Application styling. All colors are local to the GUI."""
from pathlib import Path

STYLESHEET = """
QWidget#root { background: #0b1220; }
QScrollArea { background: #0b1220; border: none; }
QScrollBar:vertical { background: #0b1220; width: 10px; margin: 2px; }
QScrollBar::handle:vertical { background: #33465f; border-radius: 4px; min-height: 25px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QWidget { color: #e5edf7; font-family: 'Segoe UI'; font-size: 10pt; }
QLabel#title { color: #f8fafc; font-size: 22pt; font-weight: 700; }
QLabel#subtitle { color: #94a3b8; font-size: 10pt; }
QLabel#identity { color: #dbeafe; font-weight: 600; padding: 5px 0; }
QLabel#hint { color: #94a3b8; font-size: 9pt; }
QLabel#status { color: #a5b4c8; font-size: 9pt; padding: 3px 0; }
QStatusBar { background: #0b1220; border-top: 1px solid #25364e; }
QLabel#credit { color: #64748b; font-size: 8pt; padding: 3px 12px; }
QGroupBox {
    background: #131e30;
    border: 1px solid #25364e;
    border-radius: 13px;
    margin-top: 13px;
    padding: 15px 14px 13px 14px;
    font-size: 10pt;
    font-weight: 600;
    color: #f1f5f9;
}
QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 17px;
    padding: 0 7px;
    color: #cbd5e1;
    background: #131e30;
}
QLineEdit, QComboBox, QSpinBox {
    background: #0d1728;
    color: #f1f5f9;
    border: 1px solid #33445d;
    border-radius: 8px;
    min-height: 35px;
    padding: 2px 10px;
    selection-background-color: #2277c8;
}
QComboBox { padding: 2px 42px 2px 14px; }
QComboBox::drop-down {
    subcontrol-origin: padding;
    subcontrol-position: top right;
    width: 34px;
    border-left: 1px solid #33445d;
    border-top-right-radius: 7px;
    border-bottom-right-radius: 7px;
    background: #142238;
}
QComboBox::drop-down:hover { background: #1d314c; }
QComboBox::down-arrow {
    image: url(APP_ARROW_URL);
    width: 12px;
    height: 12px;
}
QSpinBox { padding: 2px 30px 2px 10px; }
QSpinBox::up-button, QSpinBox::down-button {
    subcontrol-origin: border;
    width: 24px;
    border-left: 1px solid #33445d;
    background: #142238;
}
QSpinBox::up-button {
    subcontrol-position: top right;
    border-bottom: 1px solid #33445d;
    border-top-right-radius: 7px;
}
QSpinBox::down-button {
    subcontrol-position: bottom right;
    border-bottom-right-radius: 7px;
}
QSpinBox::up-button:hover, QSpinBox::down-button:hover { background: #1d314c; }
QSpinBox::up-arrow {
    image: url(APP_UP_ARROW_URL);
    width: 10px;
    height: 10px;
}
QSpinBox::down-arrow {
    image: url(APP_ARROW_URL);
    width: 10px;
    height: 10px;
}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus { border: 1px solid #38bdf8; }
QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled { color: #64748b; background: #142033; }
QComboBox QAbstractItemView {
    background: #142033;
    color: #f1f5f9;
    border: 1px solid #33445d;
    selection-background-color: #155e9d;
    padding: 4px;
}
QPushButton {
    background: #24344c;
    color: #e2e8f0;
    border: 1px solid #33465f;
    border-radius: 8px;
    min-height: 36px;
    padding: 3px 14px;
    font-weight: 600;
}
QPushButton:hover { background: #304663; border-color: #4a6688; }
QPushButton:pressed { background: #1c2b40; }
QPushButton:disabled { background: #1b293a; color: #66768d; border-color: #25364b; }
QPushButton#primary { background: #0284c7; color: #ffffff; border-color: #0ea5e9; }
QPushButton#primary:hover { background: #0ea5e9; }
QPushButton#primary:disabled { background: #1e3a53; color: #7895ab; border-color: #29435b; }
QPushButton#quiet { background: transparent; border-color: #33445d; }
QPushButton#quiet:hover { background: #23344b; }
QProgressBar {
    background: #0d1728;
    border: 1px solid #273951;
    border-radius: 6px;
    min-height: 12px;
    max-height: 12px;
    text-align: center;
    color: transparent;
}
QProgressBar::chunk { background: #22c55e; border-radius: 5px; }
QPlainTextEdit {
    background: #0a1424;
    color: #cbd5e1;
    border: 1px solid #304159;
    border-radius: 9px;
    padding: 8px;
    font-family: Consolas;
    font-size: 9pt;
    selection-background-color: #1d4e75;
}
QMessageBox { background: #131e30; }
"""

STYLESHEET = STYLESHEET.replace(
    "APP_ARROW_URL", (Path(__file__).parent / "assets" / "chevron-down.png").as_posix()
)
STYLESHEET = STYLESHEET.replace(
    "APP_UP_ARROW_URL", (Path(__file__).parent / "assets" / "chevron-up.png").as_posix()
)
