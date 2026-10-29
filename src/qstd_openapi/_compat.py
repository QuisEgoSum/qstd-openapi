"""Python version differences."""

from __future__ import annotations

import sys

from collections.abc import Mapping
from typing import Any, get_origin

from typing_extensions import TypeGuard


def is_class(obj: object) -> TypeGuard[type[Any]]:
    """``isinstance(obj, type)`` without parametrized generics.

    On Python 3.9 and 3.10 ``isinstance(list[int], type)`` is ``True``, and a
    following ``issubclass`` against an ABC raises ``TypeError``.
    """
    return isinstance(obj, type) and get_origin(obj) is None


def own_annotations(klass: type) -> Mapping[str, object]:
    """Annotations declared in the class body itself, not inherited, unevaluated.

    Since Python 3.14 (PEP 649) annotations are lazy: a class from a module
    without ``from __future__ import annotations`` has no ``__annotations__``
    key in its ``__dict__``. Use the ``__annotations__`` key directly only on
    3.9, where ``inspect.get_annotations`` does not exist yet. Names that
    cannot be resolved stay forward references; evaluating them is left to
    ``typing.get_type_hints``.
    """
    if sys.version_info >= (3, 14):
        import annotationlib

        return annotationlib.get_annotations(
            klass,
            format=annotationlib.Format.FORWARDREF,
        )
    if sys.version_info >= (3, 10):
        import inspect

        return inspect.get_annotations(klass)
    annotations: Mapping[str, object] = vars(klass).get('__annotations__', {})
    return annotations
