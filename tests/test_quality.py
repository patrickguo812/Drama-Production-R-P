import unittest

from drama_studio.models import ProjectData, Scene
from drama_studio.pipeline import demo_project
from drama_studio.providers import ChatProvider, ProviderConfig
from drama_studio.quality import apply_scene_feedback, inspect_prompt, inspect_scene, renumber_scenes


class QualityTests(unittest.TestCase):
    def scene(self, **changes):
        data = {"prompt_id": "E001_S001", "episode": 1, "scene": 1, "plot": "人物进入汽车", "location": "停车场",
                "characters": ["LIN"], "action": "人物开门，然后进入车内。", "duration_seconds": 6,
                "shot": "镜头连续跟拍人物进入车内", "continuity": "服装道具保持一致"}
        data.update(changes); return Scene.from_dict(data)

    def test_transition_word_is_warning_not_split(self):
        issues = inspect_scene(self.scene())
        self.assertIn("transition_review", [issue.code for issue in issues])
        self.assertNotIn("explicit_cut", [issue.code for issue in issues])

    def test_explicit_cut_and_over_ten_require_split(self):
        issues = inspect_scene(self.scene(duration_seconds=12, shot="车外跟拍，随后切至车内面部特写"))
        split_codes = {issue.code for issue in issues if issue.severity == "split"}
        self.assertEqual(split_codes, {"duration_over_10", "explicit_cut"})

    def test_renumber_after_split(self):
        scenes = [self.scene(), self.scene(prompt_id="bad", scene=9), self.scene(prompt_id="E002", episode=2)]
        renumber_scenes(scenes)
        self.assertEqual([scene.prompt_id for scene in scenes], ["E001_S001", "E001_S002", "E002_S001"])

    def test_demo_feedback_splits_and_clears_prompts(self):
        project = demo_project()
        provider = ChatProvider(ProviderConfig("Demo", "", "demo"))
        replacements, report = apply_scene_feedback(project, 0, "Split the camera setups", provider, "rules")
        self.assertEqual(len(replacements), 2)
        self.assertTrue(report)
        self.assertTrue(all(not scene.photo_prompt and scene.photo_status == "missing" for scene in replacements))

    def test_character_aware_prompt_checker_requires_visible_anchors(self):
        project = demo_project(); scene = project.scenes[0]
        scene.photo_prompt = "一名人物站在厨房里，中近景。"
        codes = {issue.code for issue in inspect_prompt(scene, "photo", project)}
        self.assertIn("identity_anchor_missing", codes)
        scene.photo_prompt = "26岁中国女性，椭圆脸窄下颌，左眼下泪痣，站在厨房里。"
        codes = {issue.code for issue in inspect_prompt(scene, "photo", project)}
        self.assertNotIn("identity_anchor_missing", codes)


if __name__ == "__main__": unittest.main()
