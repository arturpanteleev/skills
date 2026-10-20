import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("skills", Path(__file__).resolve().parents[1] / "tools/skills.py")
skills = importlib.util.module_from_spec(spec)
spec.loader.exec_module(skills)


class CatalogTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.repo = self.root / "repo"
        self.home = self.root / "home"
        self.repo.mkdir()
        self.home.mkdir()
        self.source = self.make_skill(self.repo / "skills/example")

    def make_skill(self, path, name="example", text="original"):
        path.mkdir(parents=True)
        (path / "references").mkdir()
        (path / "references/detail.md").write_text(text)
        (path / "SKILL.md").write_text(f'---\nname: {name}\ndescription: "A useful workflow"\n---\n[Details](references/detail.md)\n')
        return path

    def test_shared_edits_and_repeat_install(self):
        rows = skills.install(self.repo, self.home)
        self.assertEqual(len(rows), 3)
        link = self.home / ".claude/skills/example"
        before = link.lstat().st_ino
        (link / "references/detail.md").write_text("edited via Claude")
        for root in skills.harnesses(self.home).values():
            self.assertEqual((root / "example/references/detail.md").read_text(), "edited via Claude")
        skills.install(self.repo, self.home)
        self.assertEqual(before, link.lstat().st_ino)

    def test_conflict_preflight_does_not_partially_install(self):
        conflict = self.home / ".config/opencode/skills/example"
        self.make_skill(conflict, text="foreign")
        with self.assertRaises(skills.SkillError):
            skills.install(self.repo, self.home)
        self.assertFalse((self.home / ".codex/skills/example").exists())
        self.assertEqual((conflict / "references/detail.md").read_text(), "foreign")

    def test_replace_retains_backup(self):
        conflict = self.make_skill(self.home / ".claude/skills/example", text="foreign")
        rows = skills.install(self.repo, self.home, replace=True)
        row = next(r for r in rows if r["harness"] == "claude")
        self.assertEqual((Path(row["backup"]) / "references/detail.md").read_text(), "foreign")
        self.assertEqual(conflict.resolve(), self.source)

    def test_dry_run_does_not_create_destinations(self):
        skills.install(self.repo, self.home, dry_run=True)
        self.assertEqual(list(self.home.iterdir()), [])

    def test_uninstall_preserves_foreign_and_catalog(self):
        skills.install(self.repo, self.home)
        link = self.home / ".claude/skills/example"
        link.unlink()
        self.make_skill(link, text="foreign")
        skills.uninstall(self.repo, self.home, ["example"])
        self.assertEqual((link / "references/detail.md").read_text(), "foreign")
        self.assertTrue(self.source.exists())
        self.assertFalse((self.home / ".codex/skills/example").is_symlink())

    def test_import_rename_copies_references_and_invocation(self):
        origin = self.make_skill(self.root / "old-skill", name="old-skill")
        (origin / "agents").mkdir()
        (origin / "agents/openai.yaml").write_text('interface:\n  default_prompt: "Use $old-skill"\n')
        result = skills.import_skill(self.repo, origin, "new-skill")
        dest = Path(result["path"])
        self.assertEqual(skills.check_skill(dest), "new-skill")
        self.assertIn("$new-skill", (dest / "agents/openai.yaml").read_text())
        self.assertTrue((dest / "references/detail.md").exists())
        self.assertIn("name: old-skill", (origin / "SKILL.md").read_text())
        with self.assertRaises(skills.SkillError):
            skills.import_skill(self.repo, origin, "new-skill")

    def test_import_from_harness_symlink(self):
        link = self.root / "installed"
        link.symlink_to(self.source)
        result = skills.import_skill(self.repo, link, "new-name")
        self.assertEqual(skills.check_skill(Path(result["path"])), "new-name")

    def test_bad_reference_or_symlink_is_rejected(self):
        (self.source / "references/detail.md").unlink()
        with self.assertRaises(skills.SkillError):
            skills.check_skill(self.source)
        (self.source / "references/detail.md").symlink_to(self.root / "outside")
        with self.assertRaises(skills.SkillError):
            skills.check_skill(self.source)

    def test_scan_finds_links_nested_skills_and_divergence(self):
        skills.install(self.repo, self.home)
        self.make_skill(self.home / ".claude/skills/synced/team/example", text="different")
        rows = skills.scan(self.repo, self.home)
        self.assertEqual(len(rows), 5)
        self.assertTrue(all(r["diverged"] for r in rows))
        self.assertTrue(any(r["source"] == str(self.source) and r["harness"] == "codex" for r in rows))

    def test_failure_rolls_back_links_and_displaced_directory(self):
        foreign = self.make_skill(self.home / ".claude/skills/example", text="foreign")
        original = Path.symlink_to
        def fail_on_opencode(path, *args, **kwargs):
            if "opencode" in str(path):
                raise OSError("simulated failure")
            return original(path, *args, **kwargs)
        with patch.object(Path, "symlink_to", fail_on_opencode):
            with self.assertRaises(OSError):
                skills.install(self.repo, self.home, replace=True)
        self.assertFalse((self.home / ".codex/skills/example").exists())
        self.assertFalse(foreign.is_symlink())
        self.assertEqual((foreign / "references/detail.md").read_text(), "foreign")

    def test_traversal_name_rejected(self):
        with self.assertRaises(skills.SkillError):
            skills.catalog(self.repo, ["../escape"])


if __name__ == "__main__":
    unittest.main()
