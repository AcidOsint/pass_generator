"""Q3 PASS core: character classes, password generation and entropy.

This module performs no I/O. It is the only module that imports ``secrets``.
"""

from __future__ import annotations

import itertools
import math
import secrets
import string
from dataclasses import dataclass, field

LOWER = string.ascii_lowercase
UPPER = string.ascii_uppercase
DIGITS = string.digits
SYMBOLS = string.punctuation
AMBIGUOUS = "0Oo1lI|"

# Every character that can ever appear in a password, in a fixed order.
BASE_CHARS = LOWER + UPPER + DIGITS + SYMBOLS

MIN_LENGTH = 8
MAX_LENGTH = 64
DEFAULT_LENGTH = 16
MAX_ATTEMPTS = 100_000


class PolicyError(ValueError):
    """Invalid generation settings. Messages never contain a password."""


@dataclass(frozen=True)
class Policy:
    length: int = DEFAULT_LENGTH
    use_lower: bool = True
    use_upper: bool = True
    use_digits: bool = True
    use_symbols: bool = True
    exclude_ambiguous: bool = True
    excluded_chars: frozenset[str] = frozenset()
    require_each: bool = True


@dataclass(frozen=True)
class Result:
    password: str = field(repr=False)
    entropy_bits: float
    alphabet_size: int


def normalize_exclusions(text: str) -> frozenset[str]:
    """Keep only characters that belong to the base alphabet."""
    return frozenset(ch for ch in text if ch in BASE_CHARS)


def build_classes(policy: Policy) -> tuple[str, ...]:
    """Return the effective character set of every enabled class.

    Raises PolicyError if the policy cannot produce a password.
    """
    if not isinstance(policy.length, int) or isinstance(policy.length, bool):
        raise PolicyError("length must be a number")
    if not MIN_LENGTH <= policy.length <= MAX_LENGTH:
        raise PolicyError(f"length must be between {MIN_LENGTH} and {MAX_LENGTH}")

    enabled = [
        (name, chars)
        for name, chars, on in (
            ("lowercase", LOWER, policy.use_lower),
            ("uppercase", UPPER, policy.use_upper),
            ("digits", DIGITS, policy.use_digits),
            ("symbols", SYMBOLS, policy.use_symbols),
        )
        if on
    ]
    if not enabled:
        raise PolicyError("at least one character class must be enabled")

    removed = set(policy.excluded_chars)
    if policy.exclude_ambiguous:
        removed.update(AMBIGUOUS)

    classes = []
    for name, chars in enabled:
        kept = "".join(ch for ch in chars if ch not in removed)
        if not kept:
            raise PolicyError(f"{name} has no characters left after exclusions")
        classes.append(kept)

    if policy.require_each and policy.length < len(classes):
        raise PolicyError("length is shorter than number of required classes")
    return tuple(classes)


def _check_classes(classes: tuple[str, ...], length: int, require_each: bool) -> str:
    if length < 1:
        raise PolicyError("length must be positive")
    if not classes or any(not c for c in classes):
        raise PolicyError("at least one non-empty character class is required")
    alphabet = "".join(classes)
    if len(set(alphabet)) != len(alphabet):
        raise PolicyError("character classes must not overlap or repeat characters")
    if require_each and length < len(classes):
        raise PolicyError("length is shorter than number of required classes")
    return alphabet


def generate_from_classes(classes: tuple[str, ...], length: int, require_each: bool) -> str:
    """Uniformly pick ``length`` characters; with ``require_each``, reject until every class is present."""
    alphabet = _check_classes(classes, length, require_each)
    class_sets = [frozenset(c) for c in classes]
    for _ in range(MAX_ATTEMPTS):
        candidate = "".join(secrets.choice(alphabet) for _ in range(length))
        if not require_each or all(not s.isdisjoint(candidate) for s in class_sets):
            return candidate
    raise PolicyError("constraints too strict, adjust settings")


def count_valid(classes: tuple[str, ...], length: int, require_each: bool) -> int:
    """Exact number of strings the generator can output (all equally likely)."""
    _check_classes(classes, length, require_each)
    sizes = [len(c) for c in classes]
    total = sum(sizes)
    if not require_each:
        return total**length
    count = 0
    for r in range(len(sizes) + 1):
        for subset in itertools.combinations(sizes, r):
            count += (-1) ** r * (total - sum(subset)) ** length
    return count


def entropy_bits(classes: tuple[str, ...], length: int, require_each: bool) -> float:
    return math.log2(count_valid(classes, length, require_each))


def generate(policy: Policy) -> Result:
    classes = build_classes(policy)
    password = generate_from_classes(classes, policy.length, policy.require_each)
    return Result(
        password=password,
        entropy_bits=entropy_bits(classes, policy.length, policy.require_each),
        alphabet_size=sum(len(c) for c in classes),
    )
