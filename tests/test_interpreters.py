"""Unit tests for interpreter-related utilities.

Covers:
  - pyzo/util/interpreters/pythoninterpreter.py :: versionStringToTuple
  - pyzo/__init__.py :: parse_version_crudely
"""

import pytest

from pyzo.util.interpreters.pythoninterpreter import versionStringToTuple
from pyzo.util import parse_version_crudely


# ---------------------------------------------------------------------------
# versionStringToTuple
# ---------------------------------------------------------------------------


class TestVersionStringToTuple:
    def test_three_part_version(self):
        assert versionStringToTuple("3.10.5") == (3, 10, 5)

    def test_two_part_version(self):
        assert versionStringToTuple("2.7") == (2, 7)

    def test_single_number(self):
        assert versionStringToTuple("3") == (3,)

    def test_alpha_suffix_ignored(self):
        # "3.10.0a1": the function strips non-numeric/dot chars, leaving
        # "3.10.01" → parsed as (3, 10, 1). The trailing digit of the
        # suffix is absorbed into the last numeric component.
        assert versionStringToTuple("3.10.0a1") == (3, 10, 1)

    def test_beta_suffix_ignored(self):
        # "3.9.0b2" → "3.9.02" → (3, 9, 2)
        assert versionStringToTuple("3.9.0b2") == (3, 9, 2)

    def test_release_candidate_suffix_ignored(self):
        # "3.11.0rc1" → "3.11.01" → (3, 11, 1)
        assert versionStringToTuple("3.11.0rc1") == (3, 11, 1)

    def test_dev_suffix_ignored(self):
        # "3.12.0.dev0" → numeric parts: 3, 12, 0, 0
        assert versionStringToTuple("3.12.0.dev0") == (3, 12, 0, 0)

    def test_leading_zeros_parsed(self):
        assert versionStringToTuple("3.09.01") == (3, 9, 1)

    def test_large_minor_version(self):
        assert versionStringToTuple("3.100.0") == (3, 100, 0)

    def test_pypy_version_string(self):
        # PyPy may report "2.7.18" style
        assert versionStringToTuple("2.7.18") == (2, 7, 18)

    def test_version_comparison_ordering(self):
        assert versionStringToTuple("3.9.0") < versionStringToTuple("3.10.0")
        assert versionStringToTuple("3.10.0") < versionStringToTuple("3.10.1")
        assert versionStringToTuple("2.7.18") < versionStringToTuple("3.0.0")

    def test_empty_string_returns_empty_tuple(self):
        assert versionStringToTuple("") == ()

    def test_non_numeric_only_string_returns_empty_tuple(self):
        assert versionStringToTuple("abc") == ()


# ---------------------------------------------------------------------------
# parse_version_crudely  (pyzo/__init__.py)
# ---------------------------------------------------------------------------


class TestParseVersionCrudely:
    def test_three_part_version(self):
        assert parse_version_crudely("1.2.3") == (1, 2, 3)

    def test_two_part_version(self):
        assert parse_version_crudely("1.0") == (1, 0)

    def test_single_number(self):
        # The function prepends a dot before searching: "." + "3" = ".3"
        # re.findall(r"\.(\d+)", ".3") captures ["3"] → (3,)
        assert parse_version_crudely("3") == (3,)

    def test_alpha_suffix(self):
        assert parse_version_crudely("1.2.3a4") == (1, 2, 3)

    def test_leading_non_numeric(self):
        # "v1.2.3" prepended: ".v1.2.3" — the dot before "v" is not
        # followed directly by digits, so only ".2" and ".3" match.
        assert parse_version_crudely("v1.2.3") == (2, 3)

    def test_version_comparison_ordering(self):
        assert parse_version_crudely("1.9.0") < parse_version_crudely("1.10.0")
        assert parse_version_crudely("1.0.0") < parse_version_crudely("2.0.0")

    def test_returns_tuple_of_ints(self):
        result = parse_version_crudely("3.10.5")
        assert isinstance(result, tuple)
        assert all(isinstance(n, int) for n in result)
