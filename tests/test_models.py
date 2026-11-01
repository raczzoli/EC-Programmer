# SPDX-FileCopyrightText: 2026 R89 Repairs and contributors
# SPDX-License-Identifier: GPL-2.0-or-later

import unittest
from app.models import FAMILIES, FAMILIES_BY_MANUFACTURER


class ModelCatalogTests(unittest.TestCase):
    def test_catalog_and_capabilities(self):
        self.assertEqual(list(FAMILIES_BY_MANUFACTURER), ["ITE"])
        self.assertEqual([f.name for f in FAMILIES], ["IT51xx", "IT55xx", "IT8xxx"])
        self.assertEqual([f.read_protocol for f in FAMILIES], [False, False, True])


if __name__ == "__main__": unittest.main()
