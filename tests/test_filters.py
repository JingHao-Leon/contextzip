"""Pins down exclusion matching so the pathspec backend can change safely."""

from __future__ import annotations

from contextzip.filters import build_force_include_spec, build_spec, resolve_files
from tests.helpers import TempProject


class SpecMatchingTests(TempProject):
    def spec(self, *extra, modules=("base",), gitignore=None):
        gi = None
        if gitignore is not None:
            gi = self.write(".gitignore", gitignore)
        return build_spec(rule_modules=list(modules), extra_exclude=list(extra) or None, gitignore_path=gi)

    def test_base_rules(self):
        s = self.spec()
        for path in [".git/config", "a/.git/config", ".env", "app/.env.local", "x.log", "logs/a.txt", "img/a.png", ".contextzip/x"]:
            self.assertTrue(s.match_file(path), path)
        for path in ["src/app.py", "README.md", "env.ts", "docs/guide.md"]:
            self.assertFalse(s.match_file(path), path)

    def test_directory_patterns_match_at_any_depth(self):
        s = self.spec("dist/", modules=())
        self.assertTrue(s.match_file("dist/a.js"))
        self.assertTrue(s.match_file("pkg/dist/a.js"))
        self.assertFalse(s.match_file("distance.js"))

    def test_anchored_patterns(self):
        s = self.spec("/build", "docs/internal/", modules=())
        self.assertTrue(s.match_file("build/a"))
        self.assertFalse(s.match_file("sub/build/a"))
        self.assertTrue(s.match_file("docs/internal/x.md"))
        self.assertFalse(s.match_file("other/docs/internal/x.md"))

    def test_globs(self):
        s = self.spec("*.snap", "**/fixtures/**", modules=())
        self.assertTrue(s.match_file("a/b/c.snap"))
        self.assertTrue(s.match_file("x/fixtures/y.json"))
        self.assertFalse(s.match_file("snap.ts"))

    def test_gitignore_negation(self):
        s = self.spec(modules=(), gitignore="*.log\n!keep.log\n")
        self.assertTrue(s.match_file("a.log"))
        self.assertFalse(s.match_file("keep.log"))

    def test_force_include(self):
        fi = build_force_include_spec([".env", "docs/"])
        self.assertTrue(fi.match_file(".env"))
        self.assertTrue(fi.match_file("docs/a.md"))
        self.assertFalse(fi.match_file("src/.env.example"))
        self.assertIsNone(build_force_include_spec([]))


class ResolveFilesTests(TempProject):
    def setUp(self):
        super().setUp()
        self.write("src/app.py", "x")
        self.write("src/.env", "A=1")
        self.write(".env", "A=1")
        self.write("dist/out.js", "x")
        self.write("dist/node_modules/p/i.js", "x")
        self.write("logs/app.log", "x")

    def rels(self, result):
        return sorted(p.relative_to(self.root).as_posix() for p in result.included)

    def test_default(self):
        spec = build_spec(rule_modules=["base", "node"])
        self.assertEqual(self.rels(resolve_files(self.root, spec)), ["src/app.py"])

    def test_explicit_include_brings_back_excluded_paths(self):
        spec = build_spec(rule_modules=["base", "node"])
        got = self.rels(resolve_files(self.root, spec, include_only=[".env", "dist/", "logs"]))
        self.assertEqual(got, [".env", "dist/out.js", "logs/app.log"])

    def test_including_a_folder_does_not_bring_back_its_secrets(self):
        spec = build_spec(rule_modules=["base"])
        self.assertEqual(self.rels(resolve_files(self.root, spec, include_only=["src"])), ["src/app.py"])

    def test_always_include(self):
        spec = build_spec(rule_modules=["base"])
        fi = build_force_include_spec([".env"])
        self.assertIn(".env", self.rels(resolve_files(self.root, spec, force_include=fi)))
