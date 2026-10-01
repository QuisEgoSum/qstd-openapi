"""Storing contributions on the described objects themselves.

There is no registry: every function carries an immutable record of what was
attached to it. The record lives under an attribute name derived from the
owner's ``id``. ``functools.wraps`` copies the wrapped function's
``__dict__`` into the wrapper, so with a single shared attribute name the
copy would overwrite whatever had already been attached to the wrapper
(and the same record would be read twice while walking ``__wrapped__``).
With per-owner names the copy lands next to the wrapper's own record and is
ignored when the wrapper is read.
"""

from __future__ import annotations

import functools
import inspect

from dataclasses import dataclass
from typing import Any, cast

from qstd_openapi.errors import AttachError
from qstd_openapi.meta.model import Contribution, OperationPatch, Origin

_ATTR_PREFIX = '__qstd_openapi_'


@dataclass(frozen=True)
class _Record:
    owner: object
    entries: tuple[tuple[OperationPatch, str], ...]


def _attr_name(holder: object) -> str:
    return f'{_ATTR_PREFIX}{id(holder):x}__'


def _holder(obj: object) -> object:
    """The object that actually stores metadata for ``obj``."""
    if isinstance(obj, (staticmethod, classmethod)) or inspect.ismethod(obj):
        return cast('object', obj.__func__)  # pyright: ignore[reportUnknownMemberType]
    return obj


def describe_owner(obj: object) -> str:
    module = getattr(obj, '__module__', None)
    qualname = getattr(obj, '__qualname__', None) or type(obj).__qualname__
    return f'{module}.{qualname}' if module else qualname


def attach_patch(obj: object, patch: OperationPatch, api: str) -> None:
    holder = _holder(obj)
    if not hasattr(holder, '__dict__'):
        raise AttachError(
            f'Cannot attach OpenAPI metadata to {obj!r}: '
            f'{type(holder).__qualname__} objects have no __dict__. '
            'Wrap it in a regular function and describe that function.',
        )
    name = _attr_name(holder)
    record = vars(holder).get(name)
    if not isinstance(record, _Record) or record.owner is not holder:
        record = _Record(owner=holder, entries=())
    try:
        setattr(holder, name, _Record(holder, (*record.entries, (patch, api))))
    except (AttributeError, TypeError) as exc:
        raise AttachError(
            f'Cannot attach OpenAPI metadata to {obj!r}: {exc}',
        ) from exc


def _own_record(holder: object) -> _Record | None:
    try:
        record = vars(holder).get(_attr_name(holder))
    except TypeError:
        return None
    if isinstance(record, _Record) and record.owner is holder:
        return record
    return None


def _wrap_chain(obj: object) -> list[object]:
    """Holders from the outermost object down to the innermost wrapped one."""
    chain: list[object] = []
    seen: set[int] = set()
    current: Any = obj
    while current is not None:
        holder = _holder(current)
        if id(holder) in seen:
            break
        seen.add(id(holder))
        chain.append(holder)
        nxt = getattr(holder, '__wrapped__', None)
        if nxt is None and isinstance(holder, functools.partial):
            nxt = holder.func
        current = nxt
    return chain


def read_contributions(obj: object) -> tuple[Contribution, ...]:
    """All contributions for ``obj`` in application order.

    The innermost wrapped function comes first and the outermost wrapper
    last; within one object entries keep the order they were attached in.
    """
    contributions: list[Contribution] = []
    for holder in reversed(_wrap_chain(obj)):
        record = _own_record(holder)
        if record is None:
            continue
        owner = describe_owner(holder)
        for index, (patch, api) in enumerate(record.entries):
            contributions.append(Contribution(patch, Origin(owner, api, index)))
    return tuple(contributions)
