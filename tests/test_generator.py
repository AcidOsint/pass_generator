"""Generator correctness.

The statistical tests below catch bugs in OUR mapping code (modulo bias, broken
rejection sampling). They do not and cannot prove cryptographic strength.
"""

import itertools
import math
import string
import unittest
from collections import Counter
from unittest import mock

from q3pass import generator as g


def chi2_critical(df: int, z: float = 4.7534) -> float:
    """Approximate chi-square critical value for one-sided p = 1e-6 (Wilson-Hilferty)."""
    k = 2 / (9 * df)
    return df * (1 - k + z * math.sqrt(k)) ** 3


def chi2(counts: Counter, outcomes, n: int) -> float:
    expected = n / len(outcomes)
    return sum((counts[o] - expected) ** 2 / expected for o in outcomes)


class AlphabetTests(unittest.TestCase):
    def test_default_class_sizes(self):
        sizes = [len(c) for c in g.build_classes(g.Policy())]
        self.assertEqual(sizes, [24, 24, 8, 31])

    def test_ambiguous_and_custom_exclusions_absent(self):
        excluded = frozenset("\"'\\<>")
        policy = g.Policy(length=24, excluded_chars=excluded)
        forbidden = set(g.AMBIGUOUS) | excluded
        for _ in range(10_000):
            self.assertTrue(forbidden.isdisjoint(g.generate(policy).password))

    def test_disabled_class_absent(self):
        policy = g.Policy(use_symbols=False)
        for _ in range(2_000):
            self.assertTrue(set(string.punctuation).isdisjoint(g.generate(policy).password))

    def test_normalize_exclusions_ignores_foreign_chars(self):
        self.assertEqual(g.normalize_exclusions("aя €\t1"), frozenset("a1"))


class GenerationTests(unittest.TestCase):
    def test_lengths(self):
        for length in (8, 16, 64):
            self.assertEqual(len(g.generate(g.Policy(length=length)).password), length)

    def test_chars_belong_to_alphabet(self):
        policy = g.Policy()
        alphabet = set("".join(g.build_classes(policy)))
        for _ in range(2_000):
            self.assertTrue(set(g.generate(policy).password) <= alphabet)

    def test_require_each(self):
        policy = g.Policy(length=8)
        classes = g.build_classes(policy)
        for _ in range(10_000):
            pw = g.generate(policy).password
            for cls in classes:
                self.assertFalse(set(cls).isdisjoint(pw))

    def test_result_repr_hides_password(self):
        result = g.generate(g.Policy())
        self.assertNotIn(result.password, repr(result))
        self.assertNotIn(result.password, str(result))

    def test_uniform_on_valid_set(self):
        classes, length = ("ab", "1"), 3
        valid = [
            "".join(t) for t in itertools.product("ab1", repeat=length)
            if "1" in t and ({"a", "b"} & set(t))
        ]
        self.assertEqual(len(valid), 18)
        n = 180_000
        counts = Counter(g.generate_from_classes(classes, length, True) for _ in range(n))
        self.assertTrue(set(counts) <= set(valid), "generator produced an invalid string")
        self.assertLess(chi2(counts, valid, n), chi2_critical(len(valid) - 1))

    def test_no_modulo_bias(self):
        n = 200_000
        counts = Counter(g.generate_from_classes(("abcde",), 1, False) for _ in range(n))
        self.assertLess(chi2(counts, "abcde", n), chi2_critical(4))


class ValidationTests(unittest.TestCase):
    def assertPolicyError(self, policy, fragment):
        with self.assertRaises(g.PolicyError) as ctx:
            g.generate(policy)
        self.assertIn(fragment, str(ctx.exception))

    def test_all_classes_disabled(self):
        self.assertPolicyError(
            g.Policy(use_lower=False, use_upper=False, use_digits=False, use_symbols=False),
            "at least one character class",
        )

    def test_class_emptied_by_exclusions(self):
        self.assertPolicyError(
            g.Policy(excluded_chars=frozenset("23456789")), "digits has no characters left"
        )

    def test_length_bounds(self):
        self.assertPolicyError(g.Policy(length=7), "between 8 and 64")
        self.assertPolicyError(g.Policy(length=65), "between 8 and 64")

    def test_length_not_number(self):
        self.assertPolicyError(g.Policy(length="16"), "must be a number")
        self.assertPolicyError(g.Policy(length=True), "must be a number")

    def test_overlapping_classes_rejected(self):
        with self.assertRaises(g.PolicyError):
            g.generate_from_classes(("ab", "bc"), 4, True)

    def test_constraints_too_strict(self):
        with mock.patch.object(g, "MAX_ATTEMPTS", 0):
            self.assertPolicyError(g.Policy(), "constraints too strict")


if __name__ == "__main__":
    unittest.main()
