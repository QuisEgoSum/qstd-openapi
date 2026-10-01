"""Version-neutral schema markers.

They describe *what* the payload is; the dialect decides how a particular
OpenAPI version spells it.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Optional


@dataclass(frozen=True)
class File:
    """Binary content (an uploaded or downloaded file)."""

    description: Optional[str] = 'File'


@dataclass(frozen=True)
class FileList:
    """Several files under one form field."""

    max_items: Optional[int] = None
    description: Optional[str] = 'File'


@dataclass(frozen=True)
class FormFields:
    """A form body (``multipart/form-data`` and the like)."""

    fields: tuple[tuple[str, Any], ...]
    required: tuple[str, ...] = ()
    description: Optional[str] = None

    @classmethod
    def of(
        cls,
        fields: Mapping[str, Any],
        required: tuple[str, ...] = (),
        description: Optional[str] = None,
    ) -> FormFields:
        return cls(tuple(fields.items()), required, description)


@dataclass(frozen=True)
class Ref:
    """A schema reference inside a raw JSON Schema dict.

    ``{'type': 'array', 'items': Ref(UserDTO)}`` is resolved by the schema
    providers like any other schema reference. ``mode`` overrides the mode of
    the surrounding usage (``'validation'`` or ``'serialization'``).
    """

    target: Any
    mode: Optional[str] = None
