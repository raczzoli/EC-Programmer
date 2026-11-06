# SPDX-FileCopyrightText: 2026 R89 Repairs and contributors
# SPDX-License-Identifier: GPL-2.0-or-later

import unittest
from app.models import FAMILIES, FAMILIES_BY_MANUFACTURER


class ModelCatalogTests(unittest.TestCase):
    def test_catalog_and_capabilities(self):
        self.assertEqual(list(FAMILIES_BY_MANUFACTURER), ["ITE", "ENE"])
        self.assertEqual([f.name for f in FAMILIES], ["IT51xx", "IT55xx", "IT8xxx"])
        self.assertEqual([f.read_protocol for f in FAMILIES], [False, False, True])
        ene = FAMILIES_BY_MANUFACTURER["ENE"]
        self.assertEqual([group.name for group in ene], ["KB9012QF", "KB9022Q", "KB9028Q", "KB9052QD"])
        self.assertTrue(all(group.transport == "ene_edi" and group.read_protocol for group in ene))
        self.assertEqual(ene[-1].flash_sizes, (128*1024,))
        self.assertEqual([group.fixed_flash_size for group in ene], [128*1024]*4)
        self.assertTrue(all(group.fixed_flash_size is None for group in FAMILIES))


if __name__ == "__main__": unittest.main()
