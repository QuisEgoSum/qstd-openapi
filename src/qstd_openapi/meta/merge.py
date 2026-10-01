"""Merging contributions into a single :class:`OperationMeta`.

Collections accumulate (duplicates are dropped, first occurrence wins the
position). Single-valued fields go through a :class:`ScalarMergeStrategy`.
"""

from __future__ import annotations

from collections.abc import Hashable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Literal, Protocol, TypeVar, cast

from qstd_openapi.errors import ScalarConflictError
from qstd_openapi.meta.model import (
    BodyPart,
    Content,
    Contribution,
    Example,
    OperationMeta,
    Origin,
    Parameter,
    ParameterModel,
    Response,
    ResponseHeader,
    ResponsePart,
    StatusCode,
)
from qstd_openapi.meta.storage import read_contributions

T = TypeVar('T')


@dataclass(frozen=True)
class Located:
    value: Any
    origin: Origin


class ScalarMergeStrategy(Protocol):
    """Internal: how a single-valued field is chosen.

    Not part of the public API before 1.0; ``scalar_conflicts`` takes the
    names in :data:`SCALAR_STRATEGIES`.
    """

    def resolve(self, field: str, values: Sequence[Located]) -> Any:
        """Pick the value of ``field``; ``values`` are in application order."""
        ...


class ErrorOnConflict:
    """Different values for the same field are an error."""

    def resolve(self, field: str, values: Sequence[Located]) -> Any:
        distinct = _unique(item.value for item in values)
        if len(distinct) > 1:
            raise ScalarConflictError(
                field,
                [(item.value, item.origin) for item in values],
            )
        return values[-1].value


class LastWins:
    """The value applied last (the outermost one) wins."""

    def resolve(self, field: str, values: Sequence[Located]) -> Any:  # noqa: ARG002
        return values[-1].value


SCALAR_STRATEGIES: Mapping[str, ScalarMergeStrategy] = MappingProxyType(
    {'error': ErrorOnConflict(), 'last_wins': LastWins()},
)

ScalarConflicts = Literal['error', 'last_wins']
"""``'error'``: different values for one field fail the build; ``'last_wins'``:
the outermost decorator wins."""


def get_scalar_strategy(value: ScalarConflicts) -> ScalarMergeStrategy:
    raw = cast(object, value)  # callers may pass anything at runtime
    strategy = SCALAR_STRATEGIES.get(raw) if isinstance(raw, str) else None
    if strategy is None:
        known = ', '.join(repr(name) for name in SCALAR_STRATEGIES)
        raise ValueError(
            f'Unknown scalar_conflicts {value!r}; expected one of {known}',
        )
    return strategy


def _unique(items: Iterable[T]) -> list[T]:
    """Order-preserving de-duplication by equality (values may be unhashable)."""
    result: list[T] = []
    for item in items:
        if item not in result:
            result.append(item)
    return result


def _normalize_status(status: StatusCode) -> StatusCode:
    if isinstance(status, str) and status.isdigit():
        return int(status)
    return status


class _Merger:
    def __init__(self, strategy: ScalarMergeStrategy) -> None:
        self._strategy = strategy

    def scalar(self, field: str, values: list[Located]) -> Any:
        if not values:
            return None
        return self._strategy.resolve(field, values)

    def keyed(
        self,
        field: str,
        items: Iterable[tuple[Hashable, Any, Origin]],
    ) -> list[Any]:
        """One value per key, conflicts per key go through the strategy."""
        grouped: dict[Hashable, list[Located]] = {}
        for key, value, origin in items:
            grouped.setdefault(key, []).append(Located(value, origin))
        return [
            self.scalar(f'{field}[{key!r}]', values) for key, values in grouped.items()
        ]

    def body(
        self,
        parts: Iterable[tuple[BodyPart, Origin]],
        field: str = 'body',
    ) -> tuple[Content, ...]:
        grouped: dict[str, list[Any]] = {}
        examples: dict[str, list[tuple[str, Example, Origin]]] = {}
        for part, origin in parts:
            schemas = grouped.setdefault(part.media_type, [])
            if part.schema is not None and part.schema not in schemas:
                schemas.append(part.schema)
            examples.setdefault(part.media_type, []).extend(
                (name, example, origin) for name, example in part.examples
            )
        return tuple(
            Content(
                media,
                tuple(schemas),
                tuple(
                    zip(
                        _unique(name for name, _, _ in examples[media]),
                        self.keyed(
                            f'{field}[{media!r}].examples',
                            examples[media],
                        ),
                    ),
                ),
            )
            for media, schemas in grouped.items()
        )

    def responses(
        self,
        parts: Iterable[tuple[ResponsePart, Origin]],
    ) -> tuple[Response, ...]:
        by_status: dict[StatusCode, list[tuple[ResponsePart, Origin]]] = {}
        for part, origin in parts:
            by_status.setdefault(_normalize_status(part.status), []).append(
                (part, origin),
            )
        responses: list[Response] = []
        for status, items in by_status.items():
            description = self.scalar(
                f'responses[{status!r}].description',
                [
                    Located(part.description, origin)
                    for part, origin in items
                    if part.description is not None
                ],
            )
            content = self.body(
                (
                    (BodyPart(part.media_type, part.schema, part.examples), origin)
                    for part, origin in items
                    if part.media_type is not None
                    and (part.schema is not None or part.examples)
                ),
                f'responses[{status!r}]',
            )
            headers: list[ResponseHeader] = self.keyed(
                f'responses[{status!r}].headers',
                (
                    (header.name.lower(), header, origin)
                    for part, origin in items
                    for header in part.headers
                ),
            )
            responses.append(Response(status, description, content, tuple(headers)))
        return tuple(responses)


_SCALARS = (
    'summary',
    'description',
    'operation_id',
    'deprecated',
    'exclude',
    'webhook',
)


def merge_contributions(
    contributions: Iterable[Contribution],
    scalar_conflicts: ScalarConflicts = 'error',
) -> OperationMeta:
    merger = _Merger(get_scalar_strategy(scalar_conflicts))
    items = list(contributions)

    scalars: dict[str, Any] = {}
    for name in _SCALARS:
        located = [
            Located(getattr(item.patch, name), item.origin)
            for item in items
            if getattr(item.patch, name) is not None
        ]
        scalars[name] = merger.scalar(name, located)

    explicit: list[tuple[Hashable, Parameter, Origin]] = []
    models: list[ParameterModel] = []
    for item in items:
        for parameter in item.patch.parameters:
            if isinstance(parameter, Parameter):
                key = (parameter.location, _parameter_key(parameter))
                explicit.append((key, parameter, item.origin))
            elif parameter not in models:
                models.append(parameter)

    return OperationMeta(
        summary=scalars['summary'],
        description=scalars['description'],
        operation_id=scalars['operation_id'],
        deprecated=bool(scalars['deprecated']),
        exclude=bool(scalars['exclude']),
        webhook=scalars['webhook'],
        tags=tuple(_unique(tag for item in items for tag in item.patch.tags)),
        scopes=tuple(_unique(scope for item in items for scope in item.patch.scopes)),
        security=tuple(
            _unique(req for item in items for req in item.patch.security),
        ),
        parameters=tuple(merger.keyed('parameters', explicit)),
        parameter_models=tuple(models),
        body=merger.body(
            (part, item.origin) for item in items for part in item.patch.body
        ),
        responses=merger.responses(
            (part, item.origin) for item in items for part in item.patch.responses
        ),
        errors=tuple(_unique(err for item in items for err in item.patch.errors)),
        extra=tuple(extra for item in items for extra in item.patch.extra),
    )


def _parameter_key(parameter: Parameter) -> str:
    # Header names are case-insensitive.
    return parameter.name.lower() if parameter.location == 'header' else parameter.name


def read_operation(
    obj: object,
    scalar_conflicts: ScalarConflicts = 'error',
) -> OperationMeta:
    """Merged description of a handler, following its ``__wrapped__`` chain."""
    return merge_contributions(read_contributions(obj), scalar_conflicts)
