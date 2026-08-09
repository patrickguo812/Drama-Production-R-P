import unittest

from drama_studio.i18n import TEXT, tr


class I18nTests(unittest.TestCase):
    def test_catalogs_have_matching_keys(self):
        self.assertEqual(set(TEXT["en"]), set(TEXT["zh"]))

    def test_formats_values(self):
        self.assertEqual(tr("zh", "scenes_count", count=12), "共 12 个分镜")
        self.assertIn("12 scenes", tr("en", "scenes_count", count=12))

    def test_unknown_language_falls_back_to_english(self):
        self.assertEqual(tr("unknown", "ready"), "Ready")


if __name__ == "__main__":
    unittest.main()
