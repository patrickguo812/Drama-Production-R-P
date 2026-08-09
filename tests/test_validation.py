import unittest

from drama_studio.pipeline import demo_project, regenerate_field, regenerate_scene
from drama_studio.providers import ProviderConfig
from drama_studio.validation import normalize_project, validate_project


class DummyProvider:
    config = ProviderConfig(provider="Demo")


class ValidationTests(unittest.TestCase):
    def test_normalizes_ids_duration_and_status(self):
        data = demo_project().to_dict()
        data["scenes"][0]["prompt_id"] = ""
        data["scenes"][0]["duration_seconds"] = 99
        data["scenes"][0]["status"] = "unknown"
        project = normalize_project(data)
        self.assertEqual(project.scenes[0].prompt_id, "E001_S001")
        self.assertEqual(project.scenes[0].duration_seconds, 15)
        self.assertEqual(project.scenes[0].status, "draft")

    def test_detects_missing_profile(self):
        project = demo_project()
        project.scenes[0].characters.append("UNKNOWN")
        self.assertTrue(any("UNKNOWN" in value for value in validate_project(project)))

    def test_demo_selective_regeneration(self):
        project = demo_project()
        scene = regenerate_scene(project, 0, DummyProvider(), prompts_only=True)
        self.assertEqual(scene.prompt_id, project.scenes[0].prompt_id)
        self.assertTrue(scene.photo_prompt)
        self.assertIn("9:16", regenerate_field(project, 0, "photo_prompt", DummyProvider()))

    def test_rejects_unknown_regeneration_field(self):
        with self.assertRaises(ValueError):
            regenerate_field(demo_project(), 0, "prompt_id", DummyProvider())


if __name__ == "__main__":
    unittest.main()
