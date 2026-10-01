"""Version-neutral description of an operation.

Nothing here is OpenAPI-version specific: schemas are kept as references
(model classes, Python types, raw JSON Schema dicts, markers from
:mod:`qstd_openapi.markers`) and are resolved only when a document is built.
"""

from __future__ import annotations

from collections.abc import Hashable, Mapping
from dataclasses import dataclass, field
from typing import Any, Literal, Optional, Union

ParameterLocation = Literal['query', 'path', 'header', 'cookie']
StatusCode = Union[int, str]
"""HTTP status code, or an OpenAPI range/default key such as ``'4XX'``."""


@dataclass(frozen=True)
class Example:
    """A named example of a body, a response or a parameter (OpenAPI Example Object)."""

    value: Any
    summary: Optional[str] = None
    description: Optional[str] = None


Examples = tuple[tuple[str, Example], ...]
"""Named examples in the order they were given."""


@dataclass(frozen=True)
class Parameter:
    """A single named parameter."""

    location: ParameterLocation
    name: str
    schema: Any = str
    required: Optional[bool] = None
    """``None`` means the default: required for ``path``, optional otherwise."""
    description: Optional[str] = None
    deprecated: bool = False
    examples: Examples = ()


@dataclass(frozen=True)
class ParameterModel:
    """A model whose fields are expanded into parameters of one location."""

    location: ParameterLocation
    model: Any


@dataclass(frozen=True)
class BodyPart:
    media_type: str
    schema: Any
    """``None`` adds only ``examples`` to the media type."""
    examples: Examples = ()


@dataclass(frozen=True)
class ResponseHeader:
    name: str
    schema: Any = str
    description: Optional[str] = None
    required: bool = False


@dataclass(frozen=True)
class ResponsePart:
    status: StatusCode
    media_type: Optional[str] = None
    schema: Any = None
    """``None`` means a response without a body."""
    description: Optional[str] = None
    headers: tuple[ResponseHeader, ...] = ()
    examples: Examples = ()


@dataclass(frozen=True)
class ErrorRef:
    """An error object resolved into a response by an error provider."""

    error: Any
    media_type: str = 'application/json'


@dataclass(frozen=True)
class Security:
    """One security requirement object: all schemes listed are required together.

    Several :class:`Security` values on an operation are alternatives.
    An empty requirement means the operation may also be called anonymously.
    """

    schemes: tuple[tuple[str, tuple[str, ...]], ...] = ()


@dataclass(frozen=True)
class Webhook:
    name: str
    method: str = 'post'


@dataclass(frozen=True)
class OperationPatch:
    """What a single ``attach``/decorator call contributes.

    ``None`` scalars and empty tuples mean "not set by this call".
    """

    summary: Optional[str] = None
    description: Optional[str] = None
    operation_id: Optional[str] = None
    deprecated: Optional[bool] = None
    exclude: Optional[bool] = None
    webhook: Optional[Webhook] = None
    tags: tuple[str, ...] = ()
    scopes: tuple[Hashable, ...] = ()
    security: tuple[Security, ...] = ()
    parameters: tuple[Union[Parameter, ParameterModel], ...] = ()
    body: tuple[BodyPart, ...] = ()
    responses: tuple[ResponsePart, ...] = ()
    errors: tuple[ErrorRef, ...] = ()
    extra: tuple[Mapping[str, Any], ...] = ()


@dataclass(frozen=True)
class Origin:
    """Where a contribution came from, for diagnostics."""

    owner: str
    api: str
    index: int

    def __str__(self) -> str:
        return f'{self.owner} ({self.api} #{self.index})'


@dataclass(frozen=True)
class Contribution:
    patch: OperationPatch
    origin: Origin


@dataclass(frozen=True)
class Content:
    """Schemas accepted for one media type; several schemas mean ``oneOf``."""

    media_type: str
    schemas: tuple[Any, ...]
    examples: Examples = ()


@dataclass(frozen=True)
class Response:
    status: StatusCode
    description: Optional[str] = None
    content: tuple[Content, ...] = ()
    headers: tuple[ResponseHeader, ...] = ()


@dataclass(frozen=True)
class OperationMeta:
    """Merged description of one handler, still version-neutral."""

    summary: Optional[str] = None
    description: Optional[str] = None
    operation_id: Optional[str] = None
    deprecated: bool = False
    exclude: bool = False
    webhook: Optional[Webhook] = None
    tags: tuple[str, ...] = ()
    scopes: tuple[Hashable, ...] = ()
    security: tuple[Security, ...] = ()
    parameters: tuple[Parameter, ...] = ()
    parameter_models: tuple[ParameterModel, ...] = ()
    body: tuple[Content, ...] = ()
    responses: tuple[Response, ...] = ()
    errors: tuple[ErrorRef, ...] = ()
    extra: tuple[Mapping[str, Any], ...] = field(default=())
