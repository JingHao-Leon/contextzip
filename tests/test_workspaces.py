from __future__ import annotations

import json

from contextzip.detector import detect
from contextzip.workspaces import declared_package_dirs
from tests.helpers import TempProject


class WorkspacesTests(TempProject):
    def rels(self, dirs):
        return sorted(d.relative_to(self.root).as_posix() for d in dirs)

    def test_npm_and_yarn_workspaces(self):
        self.write("package.json", json.dumps({"workspaces": ["packages/*", "apps/web"]}))
        for d in ("packages/ui", "packages/api", "apps/web", "packages/node_modules"):
            (self.root / d).mkdir(parents=True)
        self.assertEqual(self.rels(declared_package_dirs(self.root)), ["apps/web", "packages/api", "packages/ui"])

    def test_yarn_object_form_and_negation(self):
        self.write("package.json", json.dumps({"workspaces": {"packages": ["libs/*", "!libs/old"]}}))
        (self.root / "libs" / "a").mkdir(parents=True)
        self.assertEqual(self.rels(declared_package_dirs(self.root)), ["libs/a"])

    def test_pnpm(self):
        self.write("pnpm-workspace.yaml", "packages:\n  - 'apps/*'\n  - \"tools/cli\"  # the CLI\ncatalog:\n  react: 19\n")
        (self.root / "apps" / "docs").mkdir(parents=True)
        (self.root / "tools" / "cli").mkdir(parents=True)
        self.assertEqual(self.rels(declared_package_dirs(self.root)), ["apps/docs", "tools/cli"])

    def test_cargo(self):
        self.write("Cargo.toml", '[workspace]\nmembers = [\n  "crates/*",\n  "bin/tool",\n]\n\n[profile.release]\nlto = true\n')
        (self.root / "crates" / "core").mkdir(parents=True)
        (self.root / "bin" / "tool").mkdir(parents=True)
        self.assertEqual(self.rels(declared_package_dirs(self.root)), ["bin/tool", "crates/core"])

    def test_go_work(self):
        self.write("go.work", "go 1.22\n\nuse (\n  ./api\n  ./worker // jobs\n)\nuse ./cli\n")
        for d in ("api", "worker", "cli"):
            (self.root / d).mkdir()
        self.assertEqual(self.rels(declared_package_dirs(self.root)), ["api", "cli", "worker"])

    def test_deep_package_is_detected(self):
        self.write("package.json", json.dumps({"workspaces": ["packages/*/apps/*"]}))
        self.write("packages/shop/apps/web/next.config.ts", "export default {}")
        self.write("packages/shop/apps/web/package.json", json.dumps({"dependencies": {"next": "16"}}))
        result = detect(self.root, max_scan_depth=1)
        self.assertIn("Next.js", result.ecosystems)
