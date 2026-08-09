import tempfile
import unittest
from pathlib import Path

from drama_studio.project_library import create_project, invalidate_scene_prompts, scan_projects, validate_project_name
from drama_studio.pipeline import demo_project


class ProjectLibraryTests(unittest.TestCase):
    def test_create_and_scan_project(self):
        with tempfile.TemporaryDirectory() as temp:
            root, project = create_project(temp, "My Drama")
            self.assertEqual(root, Path(temp) / "My Drama")
            self.assertTrue((root / "Source").is_dir())
            self.assertTrue((root / "Project Plan" / "project.drama").exists())
            self.assertTrue((root / "Project Genre" / "Videos").is_dir())
            self.assertEqual(scan_projects(temp)[0][1].project_name, "My Drama")

    def test_windows_safe_names(self):
        for name in ("bad/name", "CON", "bad:name"):
            with self.assertRaises(ValueError): validate_project_name(name)

    def test_scene_edit_invalidates_prompts(self):
        scene = demo_project().scenes[0]
        scene.status = scene.photo_status = scene.video_status = "approved"
        invalidate_scene_prompts(scene)
        self.assertEqual(scene.status, "draft")
        self.assertEqual(scene.photo_status, "missing")
        self.assertFalse(scene.photo_prompt)


if __name__ == "__main__": unittest.main()
