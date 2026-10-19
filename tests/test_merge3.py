from __future__ import annotations

import unittest

from contextzip.merge3 import merge3


def lines(s: str) -> list[str]:
    return s.split("\n")


BASE = lines("a\nb\nc\nd\ne\nf")


class Merge3Tests(unittest.TestCase):
    def test_changes_in_different_places_merge(self):
        ours = lines("A\nb\nc\nd\ne\nf")
        theirs = lines("a\nb\nc\nd\ne\nF")
        r = merge3(BASE, ours, theirs)
        self.assertTrue(r.clean)
        self.assertEqual(r.lines, lines("A\nb\nc\nd\ne\nF"))

    def test_adjacent_changes_merge(self):
        ours = lines("a\nB\nc\nd\ne\nf")
        theirs = lines("a\nb\nC\nd\ne\nf")
        r = merge3(BASE, ours, theirs)
        self.assertTrue(r.clean)
        self.assertEqual(r.lines, lines("a\nB\nC\nd\ne\nf"))

    def test_same_change_on_both_sides_is_clean(self):
        both = lines("a\nb\nX\nd\ne\nf")
        r = merge3(BASE, both, both)
        self.assertTrue(r.clean)
        self.assertEqual(r.lines, both)

    def test_different_changes_to_the_same_line_conflict(self):
        r = merge3(BASE, lines("a\nb\nOURS\nd\ne\nf"), lines("a\nb\nTHEIRS\nd\ne\nf"))
        self.assertFalse(r.clean)
        self.assertEqual(len(r.conflicts), 1)
        self.assertEqual(r.conflicts[0].ours, ["OURS"])
        self.assertEqual(r.conflicts[0].theirs, ["THEIRS"])

    def test_insertions_at_the_same_point_conflict(self):
        r = merge3(BASE, lines("a\nb\nmine\nc\nd\ne\nf"), lines("a\nb\nyours\nc\nd\ne\nf"))
        self.assertFalse(r.clean)

    def test_insertions_in_different_places_merge(self):
        r = merge3(BASE, lines("first\na\nb\nc\nd\ne\nf"), lines("a\nb\nc\nd\ne\nf\nlast"))
        self.assertTrue(r.clean)
        self.assertEqual(r.lines, lines("first\na\nb\nc\nd\ne\nf\nlast"))

    def test_untouched_side_takes_the_other(self):
        theirs = lines("a\nb\nc\nd\ne\nf\ng")
        self.assertEqual(merge3(BASE, BASE, theirs).lines, theirs)
        self.assertEqual(merge3(BASE, theirs, BASE).lines, theirs)

    def test_redacted_lines_keep_real_values(self):
        base = lines("A=[REDACTED]\nB=[REDACTED]\n")
        ours = lines("A=real-a\nB=real-b\n")
        theirs = lines("A=[REDACTED]\nB=[REDACTED]\nC=new\n")
        r = merge3(base, ours, theirs)
        self.assertTrue(r.clean)
        self.assertEqual(r.lines, lines("A=real-a\nB=real-b\nC=new\n"))


if __name__ == "__main__":
    unittest.main()
