import unittest
import json
from unittest.mock import patch

from drama_studio.providers import DEFAULTS, ChatProvider, ProviderConfig, parse_json_response


class FakeResponse:
    def __init__(self, content):
        self.payload = json.dumps({"choices": [{"message": {"content": content}, "finish_reason": "stop"}]}).encode()

    def __enter__(self): return self
    def __exit__(self, *_args): return False
    def read(self): return self.payload


class ProviderTests(unittest.TestCase):
    def test_openai_provider_defaults(self):
        endpoint, model = DEFAULTS["OpenAI"]
        self.assertEqual(endpoint, "https://api.openai.com/v1/chat/completions")
        self.assertTrue(model)

    def test_parse_plain_json(self):
        self.assertEqual(parse_json_response('{"status":"ok"}')["status"], "ok")

    def test_parse_fenced_json(self):
        self.assertEqual(parse_json_response('```json\n{"status":"ok"}\n```')["status"], "ok")

    def test_reject_missing_object(self):
        with self.assertRaises(ValueError):
            parse_json_response("not json")

    def test_empty_response_retries_with_backoff_then_succeeds(self):
        provider = ChatProvider(ProviderConfig("DeepSeek", "https://example.invalid", "model", "key"))
        responses = [FakeResponse(""), FakeResponse(None), FakeResponse("  "), FakeResponse('{"ok":true}')]
        with patch("drama_studio.providers.urllib.request.urlopen", side_effect=responses), patch("drama_studio.providers.time.sleep") as sleep:
            self.assertEqual(provider.complete("system", "user"), '{"ok":true}')
        self.assertEqual([call.args[0] for call in sleep.call_args_list], [2, 5, 10])


if __name__ == "__main__":
    unittest.main()
