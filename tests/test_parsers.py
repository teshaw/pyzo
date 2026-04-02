"""Unit tests for pyzo/codeeditor/parsers/python_parser.py.

Because pyzo/codeeditor/__init__.py requires Qt, we load the parser
modules directly via importlib and mock the Qt-dependent style module.
"""

import importlib.util
import os
import sys
import types

import pytest

# ---------------------------------------------------------------------------
# Bootstrap: mock Qt-dependent imports, then load parser modules directly
# ---------------------------------------------------------------------------

_BASE = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "pyzo", "codeeditor")
)


def _mock_style():
    """Install a lightweight mock of pyzo.codeeditor.style."""
    name = "pyzo.codeeditor.style"
    if name in sys.modules:
        return
    mock = types.ModuleType(name)

    class StyleFormat:
        def __init__(self):
            pass

        def update(self, s):
            pass

        def __str__(self):
            return ""

    class StyleElementDescription:
        def __init__(self, name="", description="", default_format=""):
            self.key = name

    mock.StyleFormat = StyleFormat
    mock.StyleElementDescription = StyleElementDescription
    sys.modules[name] = mock


def _load_module(module_name, rel_path):
    full_path = os.path.join(_BASE, rel_path)
    spec = importlib.util.spec_from_file_location(module_name, full_path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = mod
    spec.loader.exec_module(mod)
    return mod


# Install mock before any parser imports run
_mock_style()

_parsers = _load_module("pyzo.codeeditor.parsers", "parsers/__init__.py")
_tokens_mod = _load_module("pyzo.codeeditor.parsers.tokens", "parsers/tokens.py")
_parsers.tokens = _tokens_mod
_python_parser_mod = _load_module(
    "pyzo.codeeditor.parsers.python_parser", "parsers/python_parser.py"
)

BlockState = _parsers.BlockState
Python3Parser = _python_parser_mod.Python3Parser
Python2Parser = _python_parser_mod.Python2Parser
PythonParser = _python_parser_mod.PythonParser  # the ambiguous one

# Token classes used in assertions
from pyzo.codeeditor.parsers.tokens import (  # noqa: E402 (after bootstrap)
    KeywordToken,
    CommentToken,
    StringToken,
    IdentifierToken,
    NonIdentifierToken,
    FunctionNameToken,
    ClassNameToken,
    BuiltinsToken,
    NumberToken,
    OpenParenToken,
    CloseParenToken,
    UnterminatedStringToken,
)

# MultilineStringToken is defined in python_parser, not tokens
MultilineStringToken = _python_parser_mod.MultilineStringToken


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def token_types(line, previousState=0, parser=None):
    """Return a list of (token_text, token_class) for a line."""
    if parser is None:
        parser = Python3Parser()
    tokens = parser.parseLine(line, previousState)
    return [(str(t), type(t)) for t in tokens]


def token_classes(line, previousState=0, parser=None):
    return [cls for _, cls in token_types(line, previousState, parser)]


def find_token(line, text, previousState=0, parser=None):
    """Return the token class for the first token whose text equals *text*."""
    for tok_text, tok_cls in token_types(line, previousState, parser):
        if tok_text == text:
            return tok_cls
    return None


# ---------------------------------------------------------------------------
# Keywords
# ---------------------------------------------------------------------------


class TestKeywords:
    def test_def_is_keyword(self):
        assert find_token("def foo():", "def") is KeywordToken

    def test_class_is_keyword(self):
        assert find_token("class Bar:", "class") is KeywordToken

    def test_if_is_keyword(self):
        assert find_token("if x:", "if") is KeywordToken

    def test_return_is_keyword(self):
        assert find_token("return x", "return") is KeywordToken

    def test_import_is_keyword(self):
        assert find_token("import os", "import") is KeywordToken

    def test_for_is_keyword(self):
        assert find_token("for i in lst:", "for") is KeywordToken

    def test_while_is_keyword(self):
        assert find_token("while True:", "while") is KeywordToken

    def test_async_is_keyword(self):
        assert find_token("async def foo():", "async") is KeywordToken

    def test_await_is_keyword(self):
        assert find_token("    await coro()", "await") is KeywordToken

    def test_plain_identifier_not_keyword(self):
        assert find_token("my_variable = 1", "my_variable") is not KeywordToken


# ---------------------------------------------------------------------------
# Builtins
# ---------------------------------------------------------------------------


class TestBuiltins:
    def test_len_is_builtin(self):
        assert find_token("len(lst)", "len") is BuiltinsToken

    def test_print_is_builtin(self):
        assert find_token("print(x)", "print") is BuiltinsToken

    def test_range_is_builtin(self):
        assert find_token("range(10)", "range") is BuiltinsToken

    def test_isinstance_is_builtin(self):
        assert find_token("isinstance(x, int)", "isinstance") is BuiltinsToken


# ---------------------------------------------------------------------------
# Comments
# ---------------------------------------------------------------------------


class TestComments:
    def test_inline_comment(self):
        assert find_token("x = 1  # comment", "# comment") is CommentToken

    def test_full_line_comment(self):
        classes = token_classes("# this is a comment")
        # All tokens should be comment-related
        assert any(issubclass(c, CommentToken) for c in classes)

    def test_todo_comment(self):
        from pyzo.codeeditor.parsers.tokens import TodoCommentToken

        cls = find_token("# TODO: fix this", "# TODO: fix this")
        assert cls is TodoCommentToken

    def test_fixme_comment(self):
        from pyzo.codeeditor.parsers.tokens import TodoCommentToken

        cls = find_token("# fixme: broken", "# fixme: broken")
        assert cls is TodoCommentToken


# ---------------------------------------------------------------------------
# Strings
# ---------------------------------------------------------------------------


class TestStrings:
    def test_double_quoted_string(self):
        assert find_token('x = "hello"', '"hello"') is StringToken

    def test_single_quoted_string(self):
        assert find_token("x = 'world'", "'world'") is StringToken

    def test_multiline_string_start(self):
        tokens = Python3Parser().parseLine('x = """start')
        # Should produce a BlockState at the end indicating multiline
        block_states = [t for t in tokens if isinstance(t, BlockState)]
        assert block_states
        assert block_states[-1].state == 2  # double-quote multiline

    def test_multiline_string_triple_single(self):
        tokens = Python3Parser().parseLine("x = '''start")
        block_states = [t for t in tokens if isinstance(t, BlockState)]
        assert block_states
        assert block_states[-1].state == 1  # single-quote multiline

    def test_multiline_continuation(self):
        # Given we are inside a triple-quoted string (state=2), the parser
        # should continue treating the line as string content.
        tokens = Python3Parser().parseLine("still inside", previousState=2)
        string_tokens = [t for t in tokens if isinstance(t, (StringToken, BlockState))]
        assert string_tokens

    def test_unterminated_string(self):
        tokens = Python3Parser().parseLine("x = 'no end")
        string_tokens = [
            t for t in tokens if isinstance(t, UnterminatedStringToken)
        ]
        assert string_tokens

    def test_f_string(self):
        assert find_token("x = f'value {n}'", "f'value {n}'") is StringToken

    def test_raw_string(self):
        assert find_token(r"x = r'\n'", r"r'\n'") is StringToken


# ---------------------------------------------------------------------------
# Function and class names
# ---------------------------------------------------------------------------


class TestDefinitions:
    def test_function_name_after_def(self):
        assert find_token("def my_func():", "my_func") is FunctionNameToken

    def test_class_name_after_class(self):
        assert find_token("class MyClass:", "MyClass") is ClassNameToken

    def test_method_name_after_def(self):
        assert find_token("    def method(self):", "method") is FunctionNameToken

    def test_def_with_line_continuation(self):
        # def on one line, name on the next (previousState == 3)
        tokens = Python3Parser().parseLine("    func_name(self):", previousState=3)
        names = [str(t) for t in tokens if isinstance(t, FunctionNameToken)]
        assert "func_name" in names


# ---------------------------------------------------------------------------
# Parentheses
# ---------------------------------------------------------------------------


class TestParentheses:
    def test_open_paren(self):
        assert find_token("f(x)", "(") is OpenParenToken

    def test_close_paren(self):
        assert find_token("f(x)", ")") is CloseParenToken

    def test_open_bracket(self):
        assert find_token("a[0]", "[") is OpenParenToken

    def test_close_bracket(self):
        assert find_token("a[0]", "]") is CloseParenToken

    def test_open_brace(self):
        assert find_token("{1: 2}", "{") is OpenParenToken

    def test_close_brace(self):
        assert find_token("{1: 2}", "}") is CloseParenToken


# ---------------------------------------------------------------------------
# match / case soft keywords (Python 3.10+)
# ---------------------------------------------------------------------------


class TestMatchCase:
    def test_match_promoted_to_keyword_with_colon(self):
        assert find_token("match x:", "match") is KeywordToken

    def test_case_promoted_to_keyword_with_colon(self):
        assert find_token("    case 0:", "case") is KeywordToken

    def test_match_not_keyword_without_colon(self):
        # "match x" without a colon should NOT be a keyword
        cls = find_token("match x", "match")
        assert cls is not KeywordToken

    def test_case_not_keyword_without_colon(self):
        cls = find_token("    case (0, 0)", "case")
        assert cls is not KeywordToken

    def test_match_with_parenthesised_subject(self):
        assert find_token("match (x):", "match") is KeywordToken

    def test_case_with_open_paren(self):
        # "case [" — open bracket not yet closed: treated as keyword
        assert find_token("    case [", "case") is KeywordToken


# ---------------------------------------------------------------------------
# Identifier state (_identifierState)
# ---------------------------------------------------------------------------


class TestIdentifierState:
    def test_reset_returns_zero_initially(self):
        p = Python3Parser()
        assert p._identifierState() == 0

    def test_def_sets_state_three(self):
        p = Python3Parser()
        assert p._identifierState("def") == 3

    def test_class_sets_state_four(self):
        p = Python3Parser()
        assert p._identifierState("class") == 4

    def test_other_identifier_returns_and_resets(self):
        p = Python3Parser()
        p._identifierState("def")  # set to 3
        state = p._identifierState("foo")  # should return 3, reset to 0
        assert state == 3
        assert p._identifierState() == 0  # now reset


# ---------------------------------------------------------------------------
# Python 2 vs Python 3 parsers
# ---------------------------------------------------------------------------


class TestPython2Parser:
    def test_print_is_keyword_in_py2(self):
        p = Python2Parser()
        assert find_token("print x", "print", parser=p) is KeywordToken

    def test_exec_is_keyword_in_py2(self):
        p = Python2Parser()
        assert find_token("exec code", "exec", parser=p) is KeywordToken

    def test_nonlocal_not_keyword_in_py2(self):
        p = Python2Parser()
        cls = find_token("nonlocal x", "nonlocal", parser=p)
        assert cls is not KeywordToken


class TestPython3Parser:
    def test_print_is_builtin_in_py3(self):
        p = Python3Parser()
        assert find_token("print(x)", "print", parser=p) is BuiltinsToken

    def test_nonlocal_is_keyword_in_py3(self):
        p = Python3Parser()
        assert find_token("nonlocal x", "nonlocal", parser=p) is KeywordToken
