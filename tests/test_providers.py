import unittest

from drama_studio.providers import parse_json_response


class ProviderTests(unittest.TestCase):
    def test_parse_plain_json(self):
        self.assertEqual(parse_json_response('{"status":"ok"}')["status"], "ok")

    def test_parse_fenced_json(self):
        self.assertEqual(parse_json_response('```json\n{"status":"ok"}\n```')["status"], "ok")

    def test_reject_missing_object(self):
        with self.assertRaises(ValueError):
            parse_json_response("not json")


if __name__ == "__main__":
    unittest.main()

