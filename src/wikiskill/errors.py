"""The one base class for wikiskill's own errors.

Every module's error derives from it, so the CLI reports any of them as ``error: <message>`` and
exits non-zero without having to list each one, and a new module's error is never a traceback.
"""

from __future__ import annotations


class WikiskillError(Exception):
    """An error wikiskill reports to the user as a message, not a traceback."""
