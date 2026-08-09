import unittest

from drama_studio.ui import DramaStudioApp


class UIHelperTests(unittest.TestCase):
    def test_plain_language_subtitle_parser(self):
        result = DramaStudioApp._parse_subtitles("1.2-4.1 | 林岚 | 这是姐姐的号码。")
        self.assertEqual(result[0]["speaker"], "林岚")
        self.assertEqual(result[0]["end_seconds"], 4.1)

    def test_subtitle_parser_reports_bad_line(self):
        with self.assertRaises(ValueError):
            DramaStudioApp._parse_subtitles("bad subtitle")


if __name__ == "__main__":
    unittest.main()
