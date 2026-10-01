"""Which operations go into a document and which tags they get."""

from __future__ import annotations

from collections.abc import Hashable, Iterable
from dataclasses import dataclass
from typing import Optional, Protocol

from qstd_openapi.meta.model import OperationMeta


@dataclass(frozen=True, init=False)
class ScopeFilter:
    """Select operations by their ``scope`` labels.

    - ``include``: an operation with scopes is kept if it has at least one of
      them; ``None`` keeps every scoped operation;
    - ``exclude``: an operation with any of these scopes is dropped;
    - ``unscoped``: whether operations without scopes are kept.
    """

    include: Optional[frozenset[Hashable]] = None
    exclude: frozenset[Hashable] = frozenset()
    unscoped: bool = True

    def __init__(
        self,
        include: Optional[Iterable[Hashable]] = None,
        exclude: Iterable[Hashable] = (),
        *,
        unscoped: bool = True,
    ) -> None:
        object.__setattr__(
            self,
            'include',
            frozenset(include) if include is not None else None,
        )
        object.__setattr__(self, 'exclude', frozenset(exclude))
        object.__setattr__(self, 'unscoped', unscoped)

    def allows(self, scopes: Iterable[Hashable]) -> bool:
        labels = set(scopes)
        if not labels:
            return self.unscoped
        if labels & self.exclude:
            return False
        return self.include is None or bool(labels & self.include)


class TagRule(Protocol):
    """Extra tags for an operation; ``path`` is ``None`` for webhooks."""

    def __call__(
        self,
        path: Optional[str],
        method: str,
        meta: OperationMeta,
    ) -> Iterable[str]: ...


@dataclass(frozen=True)
class PathTag:
    """Tag operations whose path contains ``includes`` and not ``excludes``."""

    name: str
    includes: Optional[str] = None
    excludes: Optional[str] = None

    def __call__(
        self,
        path: Optional[str],
        method: str,  # noqa: ARG002
        meta: OperationMeta,  # noqa: ARG002
    ) -> Iterable[str]:
        if path is None:
            return ()
        if self.includes is not None and self.includes not in path:
            return ()
        if self.excludes is not None and self.excludes in path:
            return ()
        return (self.name,)
