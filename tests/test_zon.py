"""Unit tests for pyzo/util/zon.py (ZON serialisation)."""

import pytest

from pyzo.util.zon import (
    Dict,
    clear,
    copy,
    count,
    isstruct,
    loads,
    new,
    saves,
)


# ---------------------------------------------------------------------------
# Dict
# ---------------------------------------------------------------------------


class TestDict:
    def test_attribute_set_and_get(self):
        d = Dict()
        d.foo = 42
        assert d.foo == 42
        assert d["foo"] == 42

    def test_subscript_set_and_get(self):
        d = Dict()
        d["bar"] = "hello"
        assert d.bar == "hello"

    def test_missing_attribute_raises(self):
        d = Dict()
        with pytest.raises(AttributeError):
            _ = d.nonexistent

    def test_reserved_pure_name_raises(self):
        d = Dict()
        with pytest.raises(AttributeError):
            d.keys = "oops"

    def test_non_identifier_key_via_subscript(self):
        d = Dict()
        d["key with spaces"] = 99
        assert d["key with spaces"] == 99

    def test_repr_identifier_keys(self):
        d = Dict(x=1, y=2)
        r = repr(d)
        assert r.startswith("Dict(")
        assert "x=1" in r
        assert "y=2" in r

    def test_repr_non_identifier_keys(self):
        d = Dict()
        d["my key"] = "v"
        r = repr(d)
        assert "Dict([" in r

    def test_dir_includes_keys(self):
        d = Dict(alpha=1, beta=2)
        names = dir(d)
        assert "alpha" in names
        assert "beta" in names

    def test_dir_excludes_non_identifier_keys(self):
        d = Dict()
        d["not-valid"] = True
        assert "not-valid" not in dir(d)

    def test_isstruct_true_for_dict_instance(self):
        d = Dict()
        assert isstruct(d)

    def test_isstruct_false_for_plain_dict(self):
        assert not isstruct({"a": 1})

    def test_isstruct_false_for_non_dict(self):
        assert not isstruct(42)
        assert not isstruct(None)
        assert not isstruct("string")


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------


class TestNew:
    def test_returns_empty_dict(self):
        d = new()
        assert isinstance(d, Dict)
        assert len(d) == 0


class TestClear:
    def test_removes_all_items(self):
        d = Dict(a=1, b=2)
        clear(d)
        assert len(d) == 0


class TestCopy:
    def test_copies_flat_dict(self):
        d = Dict(a=1, b="hello")
        c = copy(d)
        assert c.a == 1
        assert c.b == "hello"
        c.a = 99
        assert d.a == 1  # original unchanged

    def test_copies_nested_dict(self):
        d = Dict()
        d.inner = Dict(x=10)
        c = copy(d)
        c.inner.x = 20
        assert d.inner.x == 10  # deep copy

    def test_copies_list(self):
        result = copy([1, 2, 3])
        assert result == [1, 2, 3]

    def test_copies_tuple_as_list(self):
        result = copy((1, 2))
        assert result == [1, 2]

    def test_immutable_pass_through(self):
        assert copy(42) == 42
        assert copy("hi") == "hi"
        assert copy(3.14) == pytest.approx(3.14)
        assert copy(None) is None


class TestCount:
    def test_single_scalar(self):
        assert count(42) == 1
        assert count("hi") == 1
        assert count(None) == 1

    def test_flat_dict(self):
        d = Dict(a=1, b=2)
        # 1 (the dict) + 1 (a) + 1 (b) = 3
        assert count(d) == 3

    def test_nested_dict(self):
        d = Dict()
        d.inner = Dict(x=1)
        # outer(1) + inner(1) + x(1) = 3
        assert count(d) == 3

    def test_list(self):
        # list(1) + 1 + 2 + 3 = 4
        assert count([1, 2, 3]) == 4

    def test_recursive_raises(self):
        d = Dict()
        d.self_ref = d
        with pytest.raises(RuntimeError, match="recursion"):
            count(d)


# ---------------------------------------------------------------------------
# Serialisation round-trips (loads / saves)
# ---------------------------------------------------------------------------


def _roundtrip(d):
    """Serialize d then deserialise and return the result."""
    text = saves(d)
    return loads(text)


class TestSerialisation:
    def test_empty_dict(self):
        d = _roundtrip(Dict())
        assert isinstance(d, Dict)
        assert len(d) == 0

    def test_integer_value(self):
        d = Dict(n=42)
        assert _roundtrip(d).n == 42

    def test_negative_integer(self):
        d = Dict(n=-7)
        assert _roundtrip(d).n == -7

    def test_float_value(self):
        d = Dict(f=3.14)
        assert _roundtrip(d).f == pytest.approx(3.14)

    def test_none_value(self):
        d = Dict(x=None)
        assert _roundtrip(d).x is None

    def test_string_value(self):
        d = Dict(s="hello world")
        assert _roundtrip(d).s == "hello world"

    def test_string_with_newline(self):
        d = Dict(s="line1\nline2")
        assert _roundtrip(d).s == "line1\nline2"

    def test_string_with_single_quote(self):
        d = Dict(s="it's a test")
        assert _roundtrip(d).s == "it's a test"

    def test_string_with_backslash(self):
        d = Dict(s="path\\to\\file")
        assert _roundtrip(d).s == "path\\to\\file"

    def test_unicode_string(self):
        d = Dict(s="héllo wörld")
        assert _roundtrip(d).s == "héllo wörld"

    def test_small_list_of_ints(self):
        d = Dict(lst=[1, 2, 3])
        assert _roundtrip(d).lst == [1, 2, 3]

    def test_small_list_of_strings(self):
        d = Dict(lst=["a", "b", "c"])
        assert _roundtrip(d).lst == ["a", "b", "c"]

    def test_small_list_of_floats(self):
        d = Dict(lst=[1.1, 2.2])
        result = _roundtrip(d).lst
        assert result == pytest.approx([1.1, 2.2])

    def test_empty_list(self):
        d = Dict(lst=[])
        assert _roundtrip(d).lst == []

    def test_nested_dict(self):
        d = Dict()
        d.inner = Dict(x=1, y=2)
        result = _roundtrip(d)
        assert result.inner.x == 1
        assert result.inner.y == 2

    def test_deeply_nested(self):
        d = Dict()
        d.a = Dict()
        d.a.b = Dict(val=99)
        assert _roundtrip(d).a.b.val == 99

    def test_mixed_types(self):
        d = Dict(i=1, f=2.5, s="hi", n=None, lst=[True, False])
        r = _roundtrip(d)
        assert r.i == 1
        assert r.f == pytest.approx(2.5)
        assert r.s == "hi"
        assert r.n is None

    def test_saves_requires_dict(self):
        with pytest.raises((ValueError, Exception)):
            saves([1, 2, 3])

    def test_loads_requires_string(self):
        with pytest.raises(ValueError):
            loads(b"bytes are not a string")


class TestLoadsRawText:
    """Test the ZON text parser directly with hand-crafted strings."""

    def test_parse_int(self):
        result = loads("n = 42\n")
        assert result.n == 42

    def test_parse_float(self):
        result = loads("f = 3.14\n")
        assert result.f == pytest.approx(3.14)

    def test_parse_null(self):
        result = loads("x = Null\n")
        assert result.x is None

    def test_parse_none(self):
        result = loads("x = None\n")
        assert result.x is None

    def test_parse_string(self):
        result = loads("s = 'hello'\n")
        assert result.s == "hello"

    def test_skip_comment_lines(self):
        text = "# this is a comment\nn = 7\n"
        result = loads(text)
        assert result.n == 7

    def test_skip_empty_lines(self):
        text = "\n\nn = 5\n\n"
        result = loads(text)
        assert result.n == 5

    def test_parse_inline_list(self):
        result = loads("lst = [1, 2, 3]\n")
        assert result.lst == [1, 2, 3]

    def test_parse_nested_dict(self):
        text = "outer = dict:\n  inner = 10\n"
        result = loads(text)
        assert isinstance(result.outer, Dict)
        assert result.outer.inner == 10
