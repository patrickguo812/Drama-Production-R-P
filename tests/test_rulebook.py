import tempfile
import unittest
from pathlib import Path

from drama_studio.models import ProjectData
from drama_studio.rulebook import active_rules, compile_rules, load_global_rules, new_rule, save_global_rules


class RulebookTests(unittest.TestCase):
    def test_defaults_compile_and_overrides_persist(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "rules.json"
            rules = load_global_rules(path)
            self.assertIn("3–6 seconds", compile_rules(rules))
            rules[0].enabled = False
            rules.append(new_rule("No montage", "Camera", "Avoid montage cuts."))
            save_global_rules(rules, path)
            loaded = load_global_rules(path)
            self.assertFalse(loaded[0].enabled)
            self.assertEqual(loaded[-1].title, "No montage")

    def test_project_rules_join_global_rules(self):
        global_rules = load_global_rules(Path("/nonexistent/rulebook.json"))
        project = ProjectData(rules=[new_rule("Local", "Style", "Use cold light.", scope="project").to_dict()])
        self.assertIn("Use cold light", compile_rules(active_rules(global_rules, project)))


if __name__ == "__main__": unittest.main()
