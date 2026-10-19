from __future__ import annotations

import unittest

from contextzip.git import GitChanges, get_changed_files
from tests.helpers import HAS_GIT, TempProject


@unittest.skipUnless(HAS_GIT, "git is not installed")
class GitChangesTests(TempProject):
    def setUp(self):
        super().setUp()
        self.git("init", "-q")
        self.write("backend/main.py", "a\n")
        self.git("add", "-A")
        self.git("commit", "-qm", "init")

    def rels(self, result: GitChanges) -> set[str]:
        return {p.relative_to(self.root).as_posix() for p in result.files}

    def test_changes_inside_an_embedded_repo_are_found(self):
        # create-next-app style: frontend/ has its own .git inside the monorepo
        self.write("frontend/app.ts", "1\n")
        self.git("init", "-q", cwd=self.root / "frontend")
        self.git("add", "-A", cwd=self.root / "frontend")
        self.git("commit", "-qm", "fe", cwd=self.root / "frontend")
        self.write("frontend/app.ts", "2\n")
        self.write("backend/main.py", "b\n")

        result = get_changed_files(self.root)
        self.assertIsInstance(result, GitChanges)
        self.assertEqual(self.rels(result), {"frontend/app.ts", "backend/main.py"})

    def test_unusual_file_names(self):
        self.write("docs/notes café.md", "x\n")
        result = get_changed_files(self.root)
        self.assertEqual(self.rels(result), {"docs/notes café.md"})

    def test_changes_outside_the_current_folder_are_kept(self):
        (self.root / "frontend").mkdir()
        self.write("backend/main.py", "changed\n")
        result = get_changed_files(self.root)
        self.assertIn("backend/main.py", self.rels(result))


if __name__ == "__main__":
    unittest.main()
