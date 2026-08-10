import unittest

from drama_studio.characters import ensure_character_profile, scene_character_context
from drama_studio.models import ProjectData, Scene


class CharacterProfileTests(unittest.TestCase):
    def profile(self, importance="minor"):
        return ensure_character_profile({
            "character_id": "LIN", "name": "林", "importance": importance,
            "identity": {"age": 28, "gender": "male", "face": "窄脸清晰下颌", "eyes": "深棕眼睛", "hair": "短黑侧分发", "build": "高挑精瘦", "distinctive_features": "右眉尾浅疤"},
            "default_costume": "深绿色保洁制服",
        })

    def test_every_character_gets_front_then_three_quarter(self):
        prompts = self.profile()["reference_prompts"]
        self.assertEqual([item["reference_type"] for item in prompts], ["face_front", "face_three_quarter"])
        self.assertIn("严格正面", prompts[0]["positive_prompt"])
        self.assertIn("三分之四", prompts[1]["positive_prompt"])

    def test_important_character_gets_full_body(self):
        prompts = self.profile("main")["reference_prompts"]
        self.assertEqual(prompts[2]["reference_type"], "full_body")
        self.assertIn("深绿色保洁制服", prompts[2]["positive_prompt"])

    def test_scene_context_contains_visible_identity(self):
        profile = self.profile("main")
        project = ProjectData(characters=[profile], scenes=[])
        scene = Scene("E001_S001", 1, 1, characters=["LIN"], character_state="制服被雨淋湿")
        context = scene_character_context(project, scene)
        self.assertIn("右眉尾浅疤", context[0]["identity_anchor"])
        self.assertEqual(context[0]["scene_state"], "制服被雨淋湿")


if __name__ == "__main__": unittest.main()
