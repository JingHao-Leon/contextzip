from __future__ import annotations

import unittest

from contextzip.guide import find_in_zip, parse, render


class GuideTests(unittest.TestCase):
    def test_template_examples_never_count(self):
        g = parse(render(snapshot="14-k3f9a2", project="shop", ecosystem="Next.js"))
        self.assertEqual(g.snapshot, "14-k3f9a2")
        self.assertEqual((g.moves, g.deletions), ([], []))

    def test_changes_are_parsed(self):
        text = render(snapshot="3-abc123", project="shop") + (
            "moved: src/old.ts -> src/new.ts\n"
            "- moved: `lib/a.py` → `lib/b.py`\n"
            "deleted: src/unused.ts\n"
            "deleted: ./tmp/x.js\n"
        )
        g = parse(text)
        self.assertEqual(g.moves, [("src/old.ts", "src/new.ts"), ("lib/a.py", "lib/b.py")])
        self.assertEqual(g.deletions, ["src/unused.ts", "tmp/x.js"])

    def test_found_at_any_depth(self):
        self.assertEqual(find_in_zip(["a/b/CONTEXTZIP.md", "x.ts", "wrap/contextzip.md"]), "wrap/contextzip.md")
        self.assertIsNone(find_in_zip(["README.md"]))


if __name__ == "__main__":
    unittest.main()
