# SPDX-FileCopyrightText: 2026 R89 Repairs and contributors
# SPDX-License-Identifier: GPL-2.0-or-later
"""Build identity shared by the source GUI and frozen release."""
import json
from pathlib import Path

_root = Path(__file__).resolve().parent.parent
VERSION = (_root / "VERSION").read_text(encoding="utf-8").strip()
_info = _root / "build-info.json"
BUILD_ID = json.loads(_info.read_text(encoding="utf-8"))["build_id"] if _info.exists() else "source"
