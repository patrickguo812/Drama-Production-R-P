import json
import tempfile
import unittest
from pathlib import Path

from drama_studio.pipeline import demo_project
from drama_studio.storage import extract_marked_prompt, load_project, render_photo_prompts, render_video_prompts, save_project


class StorageTests(unittest.TestCase):
    def test_output_contract(self):
        project = demo_project("Test")
        with tempfile.TemporaryDirectory() as temp:
            save_project(temp, project)
            root = Path(temp)
            self.assertTrue((root / "Project Plan" / "Scene Plan.json").exists())
            self.assertTrue((root / "Project Plan" / "Characters.txt").exists())
            self.assertTrue((root / "Project Genre" / "Photos Prompts.txt").exists())
            self.assertTrue((root / "Project Genre" / "Videos Prompts.txt").exists())
            self.assertTrue((root / "Project Genre" / "Character References").is_dir())
            raw_plan = json.loads((root / "Project Plan" / "Scene Plan.json").read_text(encoding="utf-8"))
            self.assertNotIn("characters", raw_plan)
            loaded = load_project(temp)
            self.assertEqual(loaded.scenes[0].prompt_id, "E001_S001")
            self.assertEqual(loaded.characters[0]["character_id"], "LIN")

    def test_prompt_blocks_are_independently_extractable(self):
        project = demo_project()
        project.scenes[0].photo_status = "approved"
        project.scenes[0].video_status = "approved"
        photo = render_photo_prompts(project)
        video = render_video_prompts(project)
        self.assertEqual(photo.count("<<<PHOTO_PROMPT_BEGIN>>>"), 1)
        self.assertIn("generate only scenes whose STATUS is APPROVED", photo)
        self.assertIn("===== PHOTO_SCENE_END E001_S001 =====", photo)
        self.assertIn("CHARACTER_REFERENCES: LIN", photo)
        self.assertEqual(video.count("<<<VIDEO_PROMPT_BEGIN>>>"), 1)
        self.assertIn("SOURCE_PHOTO: E001_S001", video)
        self.assertIn("上海公寓", extract_marked_prompt(photo, "E001_S001", "PHOTO"))
        self.assertIn("6秒", extract_marked_prompt(video, "E001_S001", "VIDEO"))

    def test_missing_prompt_is_explicit(self):
        with self.assertRaises(KeyError):
            extract_marked_prompt("", "E999_S999")

    def test_scene_plan_is_valid_json(self):
        project = demo_project()
        encoded = json.dumps(project.to_dict(), ensure_ascii=False)
        self.assertEqual(json.loads(encoded)["project_summary"]["title"], "演示小说")


if __name__ == "__main__":
    unittest.main()
