from __future__ import annotations

from contextzip.error_parser import _resolve_path
from tests.helpers import TempProject


class ResolvePathTests(TempProject):
    def setUp(self):
        super().setUp()
        self.write("frontend/app/login/page.tsx", "x")
        self.write("backend/app/login/page.tsx", "x")
        self.write("backend/main.go", "x")

    def test_relative_to_where_the_server_runs(self):
        # `npm run dev` in frontend/ prints app/login/page.tsx
        got = _resolve_path("app/login/page.tsx", self.root, self.root / "frontend")
        self.assertEqual(got, (self.root / "frontend/app/login/page.tsx").resolve())

    def test_bare_name_found_by_suffix(self):
        got = _resolve_path("main.go", self.root, None)
        self.assertEqual(got, (self.root / "backend/main.go").resolve())

    def test_ambiguous_name_prefers_the_run_folder(self):
        got = _resolve_path("login/page.tsx", self.root, self.root / "backend")
        self.assertEqual(got, (self.root / "backend/app/login/page.tsx").resolve())

    def test_ambiguous_without_a_hint_is_dropped(self):
        self.assertIsNone(_resolve_path("login/page.tsx", self.root, None))
