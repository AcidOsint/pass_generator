"""Entropy formula checked against exhaustive enumeration."""

import itertools
import math
import unittest

from q3pass import generator as g


def brute_force_count(classes, length, require_each):
    alphabet = "".join(classes)
    count = 0
    for chars in itertools.product(alphabet, repeat=length):
        if not require_each or all(set(c) & set(chars) for c in classes):
            count += 1
    return count


CONFIGS = [
    (("ab", "1"), 3),
    (("ab", "cd"), 5),
    (("a", "b", "c"), 3),
    (("ab", "12", "x"), 4),
    (("abc", "1", "#!"), 4),
    (("abc", "12", "#", "x"), 5),
]


class EntropyTests(unittest.TestCase):
    def test_without_requirement(self):
        self.assertAlmostEqual(g.entropy_bits(("abc",), 5, False), 5 * math.log2(3))
        self.assertAlmostEqual(g.entropy_bits(("ab", "1"), 7, False), 7 * math.log2(3))

    def test_inclusion_exclusion_matches_enumeration(self):
        for classes, length in CONFIGS:
            for require in (False, True):
                with self.subTest(classes=classes, length=length, require=require):
                    self.assertEqual(
                        g.count_valid(classes, length, require),
                        brute_force_count(classes, length, require),
                    )

    def test_uses_actual_alphabet(self):
        base = g.generate(g.Policy())
        reduced = g.generate(g.Policy(excluded_chars=frozenset("abc")))
        self.assertEqual(base.alphabet_size, 87)
        self.assertEqual(reduced.alphabet_size, 84)
        self.assertLess(reduced.entropy_bits, base.entropy_bits)

    def test_requirement_lowers_entropy(self):
        on = g.generate(g.Policy(require_each=True)).entropy_bits
        off = g.generate(g.Policy(require_each=False)).entropy_bits
        self.assertAlmostEqual(off, 16 * math.log2(87))
        self.assertLess(on, off)

    def test_default_value(self):
        self.assertEqual(round(g.generate(g.Policy()).entropy_bits, 1), 102.7)


if __name__ == "__main__":
    unittest.main()
