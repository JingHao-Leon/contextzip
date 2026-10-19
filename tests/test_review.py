from __future__ import annotations

import unittest

from contextzip.webui.review import _diff_rows


class DiffRowsTests(unittest.TestCase):
    def test_changed_line_gets_word_spans(self):
        rows = _diff_rows("a\nreturn 'mine'\nc\n", "a\nreturn 'theirs'\nc\n")
        mod = [r for r in rows if r["t"] == "mod"]
        self.assertEqual(len(mod), 1)
        self.assertTrue(mod[0]["ls"] and mod[0]["rs"])

    def test_long_unchanged_runs_fold(self):
        left = "\n".join(f"line {i}" for i in range(40))
        right = left.replace("line 20", "changed 20")
        rows = _diff_rows(left, right)
        folds = [r for r in rows if r["t"] == "fold"]
        self.assertEqual(len(folds), 2)
        self.assertLess(len(rows), 20)

    def test_added_and_removed_lines(self):
        rows = _diff_rows("a\nb\n", "a\nb\nc\n")
        self.assertEqual(rows[-1]["t"], "add")
        self.assertNotIn("l", rows[-1])


if __name__ == "__main__":
    unittest.main()
