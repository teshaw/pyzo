"""
Diff gutter support for the pyzo file browser.

The :class:`Hunk` dataclass and the :func:`~githelper.get_hunk_diff`
helper are the primary public API consumed by any diff-gutter widget.
"""

from .githelper import Hunk, get_hunk_diff  # noqa: F401

__all__ = ["Hunk", "get_hunk_diff"]
