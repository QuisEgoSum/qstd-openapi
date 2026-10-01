"""Python version differences."""

from __future__ import annotations

from typing import Any, get_origin

from typing_extensions import TypeGuard


def is_class(obj: object) -> TypeGuard[type[Any]]:
    """``isinstance(obj, type)`` without parametrized generics.

    On Python 3.9 and 3.10 ``isinstance(list[int], type)`` is ``True``, and a
    following ``issubclass`` against an ABC raises ``TypeError``.
    """
    return isinstance(obj, type) and get_origin(obj) is None
