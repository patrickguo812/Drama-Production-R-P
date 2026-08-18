import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from drama_studio.project_library import (TRASH_METADATA, create_project, duplicate_project,
    invalidate_scene_prompts, move_project_to_trash, permanently_delete_trash_item,
    purge_expired_trash, rename_project, restore_project, scan_projects, scan_trash,
    validate_project_name)
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

    def test_rename_and_duplicate_project(self):
        with tempfile.TemporaryDirectory() as temp:
            root, _ = create_project(temp, "Original")
            renamed, project = rename_project(temp, root, "Renamed")
            self.assertFalse(root.exists())
            self.assertEqual(project.project_name, "Renamed")
            copied, copy_project = duplicate_project(temp, renamed, "Copy")
            self.assertTrue(copied.exists())
            self.assertEqual(copy_project.project_name, "Copy")

    def test_trash_restore_and_permanent_delete(self):
        with tempfile.TemporaryDirectory() as temp:
            root, _ = create_project(temp, "Recoverable")
            trashed = move_project_to_trash(temp, root)
            self.assertTrue((trashed / TRASH_METADATA).exists())
            self.assertEqual(len(scan_trash(temp)), 1)
            restored, _ = restore_project(temp, trashed)
            self.assertEqual(restored.name, "Recoverable")
            trashed = move_project_to_trash(temp, restored)
            permanently_delete_trash_item(temp, trashed)
            self.assertFalse(trashed.exists())

    def test_purge_only_valid_items_at_ten_days(self):
        with tempfile.TemporaryDirectory() as temp:
            now = datetime(2026, 8, 10, tzinfo=timezone.utc)
            old, _ = create_project(temp, "Old")
            fresh, _ = create_project(temp, "Fresh")
            old_trash = move_project_to_trash(temp, old, now - timedelta(days=10))
            fresh_trash = move_project_to_trash(temp, fresh, now - timedelta(days=9, hours=23))
            unmarked = Path(temp) / ".DramaStudio Trash" / "Unmarked"
            unmarked.mkdir()
            removed = purge_expired_trash(temp, now=now)
            self.assertEqual(removed, [old_trash])
            self.assertFalse(old_trash.exists())
            self.assertTrue(fresh_trash.exists())
            self.assertTrue(unmarked.exists())


if __name__ == "__main__": unittest.main()
