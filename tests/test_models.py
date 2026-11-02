# SPDX-FileCopyrightText: 2026 R89 Repairs and contributors
# SPDX-License-Identifier: GPL-2.0-or-later

import unittest
from app.models import FAMILIES, FAMILIES_BY_MANUFACTURER


class ModelCatalogTests(unittest.TestCase):
    def test_catalog_and_capabilities(self):
        self.assertEqual(list(FAMILIES_BY_MANUFACTURER), ["ITE", "ENE"])
        self.assertEqual([f.name for f in FAMILIES], ["IT51xx", "IT55xx", "IT8xxx"])
        self.assertEqual([f.read_protocol for f in FAMILIES], [False, False, True])
        ene = FAMILIES_BY_MANUFACTURER["ENE"][0]
        self.assertEqual((ene.name, ene.transport, ene.read_protocol),
                         ("KB90xx EDI", "ene_edi", True))


if __name__ == "__main__": unittest.main()
