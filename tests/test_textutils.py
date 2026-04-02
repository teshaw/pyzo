"""Unit tests for pyzo/codeeditor/textutils.py (TextReshaper).

Because pyzo/codeeditor/__init__.py requires Qt, we load textutils.py
directly via importlib to avoid that dependency.
"""

import importlib.util
import os
import sys

import pytest

# ---------------------------------------------------------------------------
# Load TextReshaper without triggering the Qt-dependent package __init__
# ---------------------------------------------------------------------------

_TEXTUTILS_PATH = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "pyzo", "codeeditor", "textutils.py")
)
_spec = importlib.util.spec_from_file_location("_textutils_direct", _TEXTUTILS_PATH)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
TextReshaper = _mod.TextReshaper


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def reshape(text, lw=60):
    return TextReshaper.reshapeText(text, lw)


# ---------------------------------------------------------------------------
# Basic interface
# ---------------------------------------------------------------------------


class TestInterface:
    def test_pushtext_poptext_roundtrip(self):
        tr = TextReshaper(60)
        tr.pushText("hello world")
        result = tr.popText()
        assert "hello" in result
        assert "world" in result

    def test_pushline_poplines(self):
        tr = TextReshaper(60)
        tr.pushLine("hello world")
        lines = tr.popLines()
        assert isinstance(lines, list)
        assert len(lines) >= 1

    def test_classmethod_reshape_text(self):
        result = reshape("short line", lw=80)
        assert isinstance(result, str)

    def test_trailing_whitespace_stripped(self):
        tr = TextReshaper(60)
        tr.pushLine("hello   ")
        lines = tr.popLines()
        for line in lines:
            assert not line.endswith(" ") or not line.strip()


# ---------------------------------------------------------------------------
# Wrapping behaviour
# ---------------------------------------------------------------------------


class TestWrapping:
    def test_short_text_unchanged(self):
        text = "short"
        result = reshape(text, lw=80)
        assert "short" in result

    def test_long_line_is_wrapped(self):
        words = ["word"] * 30
        text = " ".join(words)
        result = reshape(text, lw=40)
        lines = result.splitlines()
        assert len(lines) > 1
        for line in lines:
            assert len(line) <= 44  # a little slack for long words

    def test_words_preserved_after_wrap(self):
        words = ["alpha", "beta", "gamma", "delta", "epsilon"]
        text = " ".join(words)
        result = reshape(text, lw=20)
        for word in words:
            assert word in result

    def test_single_very_long_word_appears(self):
        long_word = "a" * 100
        result = reshape(long_word, lw=40)
        assert long_word in result

    def test_multiple_paragraphs_have_blank_line(self):
        text = "first paragraph\n\nsecond paragraph"
        result = reshape(text, lw=80)
        assert "\n" in result
        # There should be a blank (or whitespace-only) line between paragraphs
        lines = result.splitlines()
        blank_found = any(line.strip() == "" for line in lines)
        assert blank_found


# ---------------------------------------------------------------------------
# Comment handling
# ---------------------------------------------------------------------------


class TestComments:
    def test_comment_prefix_preserved(self):
        text = "# This is a comment line"
        result = reshape(text, lw=80)
        assert result.lstrip().startswith("#")

    def test_comment_lines_wrapped_together(self):
        text = "# first\n# second\n# third"
        result = reshape(text, lw=80)
        assert "#" in result

    def test_indented_comment_prefix_preserved(self):
        text = "    # indented comment line here"
        result = reshape(text, lw=80)
        assert "#" in result

    def test_comment_kept_separate_from_plain_text(self):
        text = "# comment\nplain text"
        result = reshape(text, lw=80)
        lines = result.splitlines()
        comment_lines = [l for l in lines if "#" in l]
        plain_lines = [l for l in lines if "#" not in l and l.strip()]
        assert comment_lines
        assert plain_lines


# ---------------------------------------------------------------------------
# Bullet-point handling
# ---------------------------------------------------------------------------


class TestBulletPoints:
    def test_bullet_prefix_preserved(self):
        text = "* A bullet point item"
        result = reshape(text, lw=80)
        assert "* " in result

    def test_long_bullet_wrapped_with_continuation_indent(self):
        long_bullet = "* " + "word " * 30
        result = reshape(long_bullet, lw=40)
        lines = result.splitlines()
        assert lines[0].lstrip().startswith("* ")
        # Continuation lines should be indented (not start with "* ")
        if len(lines) > 1:
            for cont_line in lines[1:]:
                if cont_line.strip():
                    assert not cont_line.lstrip().startswith("* ")

    def test_multiple_bullet_points(self):
        text = "* first\n* second\n* third"
        result = reshape(text, lw=80)
        assert result.count("* ") == 3


# ---------------------------------------------------------------------------
# Indentation handling
# ---------------------------------------------------------------------------


class TestIndentation:
    def test_indented_block_preserved(self):
        text = "    indented line"
        result = reshape(text, lw=80)
        assert result.startswith("    ")

    def test_indent_change_causes_break(self):
        text = "no indent\n   indented"
        result = reshape(text, lw=80)
        lines = [l for l in result.splitlines() if l.strip()]
        assert len(lines) == 2

    def test_same_indent_words_join(self):
        text = "word1\nword2\nword3"
        result = reshape(text, lw=80)
        # All on same indent level, so they should be joined on one line
        lines = [l for l in result.splitlines() if l.strip()]
        assert len(lines) == 1
        assert "word1" in lines[0]
        assert "word2" in lines[0]
        assert "word3" in lines[0]
