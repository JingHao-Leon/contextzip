from __future__ import annotations

import unittest

from contextzip.pathmatch import match_paths

KNOWN = {
    "frontend/src/app/page.tsx",
    "frontend/src/app/login/page.tsx",
    "frontend/src/lib/auth.ts",
    "frontend/package.json",
    "backend/api/main.py",
    "README.md",
}


def targets(result):
    return {m.name: (m.target, m.how) for m in result.matches}


class MatchPathsTests(unittest.TestCase):
    def test_exact_paths(self):
        r = match_paths(["frontend/src/lib/auth.ts", "README.md"], KNOWN)
        self.assertEqual(targets(r)["frontend/src/lib/auth.ts"], ("frontend/src/lib/auth.ts", "exact"))
        self.assertIsNone(r.rule)

    def test_wrapper_folder_is_dropped(self):
        r = match_paths(["my-app/frontend/src/lib/auth.ts", "my-app/frontend/src/lib/new.ts"], KNOWN)
        t = targets(r)
        self.assertEqual(t["my-app/frontend/src/lib/auth.ts"][0], "frontend/src/lib/auth.ts")
        self.assertEqual(t["my-app/frontend/src/lib/new.ts"], ("frontend/src/lib/new.ts", "new"))

    def test_paths_relative_to_a_subfolder(self):
        r = match_paths(["src/lib/auth.ts", "src/lib/rate-limit.ts"], KNOWN)
        t = targets(r)
        self.assertEqual(t["src/lib/auth.ts"][0], "frontend/src/lib/auth.ts")
        # the new file follows its sibling into frontend/
        self.assertEqual(t["src/lib/rate-limit.ts"], ("frontend/src/lib/rate-limit.ts", "new"))

    def test_windows_separators(self):
        r = match_paths(["frontend\\src\\lib\\auth.ts"], KNOWN)
        self.assertEqual(targets(r)["frontend/src/lib/auth.ts"][0], "frontend/src/lib/auth.ts")

    def test_flattened_unique_name(self):
        r = match_paths(["auth.ts", "main.py"], KNOWN)
        t = targets(r)
        self.assertEqual(t["auth.ts"], ("frontend/src/lib/auth.ts", "suffix"))
        self.assertEqual(t["main.py"], ("backend/api/main.py", "suffix"))

    def test_flattened_ambiguous_name_uses_content(self):
        contents = {
            "frontend/src/app/page.tsx": b"export default function Home() {\n  return <main>home</main>\n}\n",
            "frontend/src/app/login/page.tsx": b"export default function Login() {\n  return <form>login</form>\n}\n",
        }
        incoming = b"export default function Login() {\n  return <form>login!</form>\n}\n"
        r = match_paths(["page.tsx"], KNOWN, read_entry=lambda n: incoming, read_known=contents.get)
        self.assertEqual(targets(r)["page.tsx"], ("frontend/src/app/login/page.tsx", "content"))

    def test_truly_ambiguous_is_never_guessed(self):
        r = match_paths(["page.tsx"], KNOWN)
        m = r.matches[0]
        self.assertIsNone(m.target)
        self.assertEqual(m.how, "ambiguous")
        self.assertEqual(len(m.candidates), 2)

    def test_prefers_files_that_were_sent(self):
        r = match_paths(["page.tsx"], KNOWN, sent={"frontend/src/app/login/page.tsx"})
        self.assertEqual(targets(r)["page.tsx"][0], "frontend/src/app/login/page.tsx")

    def test_junk_is_skipped(self):
        r = match_paths(["__MACOSX/._x", "a/.DS_Store", "README.md"], KNOWN)
        self.assertEqual([m.name for m in r.matches], ["README.md"])

    def test_never_writes_into_git_or_workspace(self):
        r = match_paths([".git/config", ".contextzip/config.json"], KNOWN)
        self.assertTrue(all(m.target is None for m in r.matches))

    def test_two_entries_never_share_a_target(self):
        r = match_paths(["frontend/src/lib/auth.ts", "x/frontend/src/lib/auth.ts"], KNOWN)
        hits = [m for m in r.matches if m.target == "frontend/src/lib/auth.ts"]
        self.assertEqual(len(hits), 1)


if __name__ == "__main__":
    unittest.main()
