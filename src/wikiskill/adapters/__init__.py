"""Readers for evaluation fixtures other projects already maintain.

An adapter reads a repository's own format in place and never writes to it. The fixtures belong to
the project that maintains them, and a runner that needs something they do not declare supplies it
on its own side rather than asking for a new field.
"""

from __future__ import annotations

from .dsh import DEFAULT_SPLIT, AdapterError, is_dsh_document, to_suite_document

__all__ = ["DEFAULT_SPLIT", "AdapterError", "is_dsh_document", "to_suite_document"]
