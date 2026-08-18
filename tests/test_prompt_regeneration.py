import json
import unittest

from drama_studio.pipeline import demo_project, regenerate_prompt_kind
from drama_studio.providers import ProviderConfig


class TruncatedOnceProvider:
    config = ProviderConfig(provider="DeepSeek", api_key="unused")

    def __init__(self):
        self.limits = []

    def complete(self, system, user, max_tokens=8192, retries=2):
        self.limits.append(max_tokens)
        if len(self.limits) == 1:
            raise RuntimeError("The provider response was truncated because this request produced too much output.")
        return json.dumps({"positive_prompt": "精确图片提示词", "negative_prompt": "多余人物"}, ensure_ascii=False)


class PromptRegenerationTests(unittest.TestCase):
    def test_retries_a_truncated_single_prompt_with_compact_limit(self):
        provider = TruncatedOnceProvider()
        positive, negative = regenerate_prompt_kind(demo_project(), 0, "photo", provider)
        self.assertEqual((positive, negative), ("精确图片提示词", "多余人物"))
        self.assertEqual(provider.limits, [1200, 900])

    def test_initial_generation_does_not_send_old_prompt_as_context(self):
        project = demo_project()
        project.scenes[0].photo_prompt = "OLD PROMPT MUST NOT BE SENT"
        provider = CapturingProvider()
        regenerate_prompt_kind(project, 0, "photo", provider, operation="generate")
        self.assertNotIn("OLD PROMPT MUST NOT BE SENT", provider.user)
        self.assertIn("首次生成", provider.user)

    def test_regeneration_sends_existing_prompt_as_revision_context(self):
        project = demo_project()
        project.scenes[0].photo_prompt = "OLD PROMPT TO REVISE"
        provider = CapturingProvider()
        regenerate_prompt_kind(project, 0, "photo", provider, operation="regenerate")
        self.assertIn("OLD PROMPT TO REVISE", provider.user)
        self.assertIn("重新生成", provider.user)


class CapturingProvider:
    config = ProviderConfig(provider="DeepSeek", api_key="unused")

    def complete(self, system, user, max_tokens=8192, retries=2):
        self.user = user
        return json.dumps({"positive_prompt": "新提示词", "negative_prompt": ""}, ensure_ascii=False)


if __name__ == "__main__":
    unittest.main()
