import shutil
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from build_plugin import PLUGIN_FILES, build_plugin, read_version


class BuildTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        shutil.copytree(ROOT / "plugin", self.root / "plugin",
                        ignore=shutil.ignore_patterns("__pycache__"))
        shutil.copyfile(ROOT / "README.md", self.root / "README.md")

    def tearDown(self):
        self.temporary.cleanup()

    def test_archive_contains_only_installable_files_at_its_root(self):
        # Unrelated local files must never leak into a release package.
        (self.root / "plugin" / "private.epub").write_bytes(b"local-only")
        (self.root / "installation-state.json").write_text("{}", encoding="utf-8")
        package = build_plugin(self.root)
        self.assertEqual(package.name, f"KindleAutoPrepare-{read_version(self.root)}.zip")
        with zipfile.ZipFile(package) as archive:
            self.assertEqual(set(archive.namelist()), {*PLUGIN_FILES, "README.md"})
            self.assertIsNone(archive.testzip())
            for name in PLUGIN_FILES:
                self.assertEqual(archive.read(name), (self.root / "plugin" / name).read_bytes())

    def test_unchanged_inputs_produce_identical_archives(self):
        first = build_plugin(self.root, self.root / "first.zip")
        second = build_plugin(self.root, self.root / "second.zip")
        self.assertEqual(first.read_bytes(), second.read_bytes())

    def test_missing_source_does_not_replace_an_existing_package(self):
        destination = self.root / "existing.zip"
        destination.write_bytes(b"previous-build")
        (self.root / "plugin" / "core.py").unlink()
        with self.assertRaises(FileNotFoundError):
            build_plugin(self.root, destination)
        self.assertEqual(destination.read_bytes(), b"previous-build")


if __name__ == "__main__":
    unittest.main()
