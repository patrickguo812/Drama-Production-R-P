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
            self.assertTrue((root / "Project Plan" / "Character Profiles" / "LIN.json").exists())
            self.assertTrue((root / "Project Genre" / "Photos Prompts.json").exists())
            self.assertTrue((root / "Project Genre" / "Videos Prompts.json").exists())
            self.assertFalse((root / "Project Plan" / "Characters.txt").exists())
            self.assertTrue((root / "Project Genre" / "Character References").is_dir())
            profile = json.loads((root / "Project Plan" / "Character Profiles" / "LIN.json").read_text(encoding="utf-8"))
            self.assertEqual([item["reference_type"] for item in profile["reference_prompts"][:2]], ["face_front", "face_three_quarter"])
            self.assertEqual(profile["reference_prompts"][0]["order"], 1)
            self.assertIn("full_body", [item["reference_type"] for item in profile["reference_prompts"]])
            raw_plan = json.loads((root / "Project Plan" / "Scene Plan.json").read_text(encoding="utf-8"))
            self.assertNotIn("characters", raw_plan)
            loaded = load_project(temp)
            self.assertEqual(loaded.scenes[0].prompt_id, "E001_S001")
            self.assertEqual(loaded.characters[0]["character_id"], "LIN")

    def test_prompt_blocks_are_independently_extractable(self):
        project = demo_project()
        project.scenes[0].photo_status = "approved"
        project.scenes[0].video_status = "approved"
        project.scenes[0].photo_negative_prompt = "人物变形，错误发型"
        photo = render_photo_prompts(project)
        video = render_video_prompts(project)
        photo_data, video_data = json.loads(photo), json.loads(video)
        self.assertEqual(photo_data["format"], "drama-photo-prompts-v2")
        self.assertEqual(photo_data["prompts"][0]["character_ids"], ["LIN"])
        self.assertEqual(photo_data["prompts"][0]["prompt_id"], "E001_S001")
        self.assertTrue(photo_data["prompts"][0]["negative_prompt_required"])
        self.assertEqual(video_data["prompts"][0]["source_photo_id"], "E001_S001")
        self.assertIn("上海公寓", extract_marked_prompt(photo, "E001_S001", "PHOTO"))
        self.assertIn("6秒", extract_marked_prompt(video, "E001_S001", "VIDEO"))

    def test_missing_prompt_is_explicit(self):
        with self.assertRaises(KeyError):
            extract_marked_prompt("", "E999_S999")

    def test_scene_plan_is_valid_json(self):
        project = demo_project()
        encoded = json.dumps(project.to_dict(), ensure_ascii=False)
        self.assertEqual(json.loads(encoded)["project_summary"]["title"], "演示小说")

    def test_save_migrates_legacy_generated_txt_files(self):
        project = demo_project()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); (root / "Project Plan").mkdir(); (root / "Project Genre").mkdir()
            for path in (root / "Project Plan" / "Scene Plan.txt", root / "Project Plan" / "Characters.txt",
                         root / "Project Genre" / "Photos Prompts.txt", root / "Project Genre" / "Videos Prompts.txt"):
                path.write_text("legacy generated output", encoding="utf-8")
            save_project(root, project)
            self.assertFalse((root / "Project Plan" / "Scene Plan.txt").exists())
            self.assertTrue((root / "Project Genre" / "Photos Prompts.json").exists())


if __name__ == "__main__":
    unittest.main()
