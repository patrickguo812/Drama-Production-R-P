import json
import unittest

from drama_studio.docx_reader import ExtractedNovel
from drama_studio.pipeline import process_novel
from drama_studio.providers import ProviderConfig


class ScriptedProvider:
    config = ProviderConfig(provider="DeepSeek", api_key="not-used")

    def __init__(self):
        self.calls = []

    def complete(self, system, user, max_tokens=8192, retries=2):
        self.calls.append(user)
        if "分析以下小说片段" in user:
            return json.dumps({"source_section": 1, "plot_events": ["event"], "characters": [], "locations": [], "themes": [], "visual_clues": []})
        if "内部改编计划" in user:
            return json.dumps({
                "project_summary": {"title": "T", "main_theme": "M", "genre": "G", "tone": "T", "visual_style": "V", "adaptation_direction": "A"},
                "characters": [{"character_id": "LIN", "name": "林"}],
                "episodes": [{"episode": 1, "title": "E", "source_sections": [1], "plot_arc": "", "opening_hook": "", "ending_hook": "", "target_scene_count": 1}],
            }, ensure_ascii=False)
        return json.dumps({"scenes": [{
            "prompt_id": "wrong", "episode": 99, "scene": 99, "plot": "P", "location": "L", "time_of_day": "N",
            "characters": ["LIN"], "character_state": "C", "action": "A", "subtitles": [], "duration_seconds": 6,
            "shot": "S", "continuity": "C", "photo_prompt": "照片", "video_prompt": "视频", "status": "draft"
        }]}, ensure_ascii=False)


class PipelineTests(unittest.TestCase):
    def test_generates_episode_batches_and_normalizes_ids(self):
        provider = ScriptedProvider()
        novel = ExtractedNovel("T", ["正文"], [("正文", "正文")])
        project = process_novel(novel, provider)
        self.assertEqual(project.scenes[0].prompt_id, "E001_S001")
        self.assertEqual(len(provider.calls), 3)

    def test_cancellation_before_provider_call(self):
        provider = ScriptedProvider()
        novel = ExtractedNovel("T", ["正文"], [("正文", "正文")])
        with self.assertRaises(InterruptedError):
            process_novel(novel, provider, cancelled=lambda: True)
        self.assertEqual(provider.calls, [])


if __name__ == "__main__":
    unittest.main()
