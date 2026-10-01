"""Exceptions raised while attaching metadata and building documents."""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from qstd_openapi.meta.model import Origin


class QstdOpenAPIError(Exception):
    """Base class for all errors raised by the library."""


class AttachError(QstdOpenAPIError, TypeError):
    """OpenAPI metadata cannot be attached to the given object."""


class BuildError(QstdOpenAPIError):
    """A document cannot be built; ``code`` is stable and machine-readable."""

    code: str = 'build-error'


class ScalarConflictError(BuildError, ValueError):
    """A single-valued field received different values from several places."""

    code = 'scalar-conflict'
    field: str
    values: tuple[tuple[Any, Origin], ...]

    def __init__(self, field: str, values: Sequence[tuple[Any, Origin]]) -> None:
        self.field = field
        self.values = tuple(values)
        listed = '; '.join(f'{value!r} from {origin}' for value, origin in self.values)
        super().__init__(
            f'Conflicting values for {field!r}: {listed}. '
            "Set it in one place or build with scalar_conflicts='last_wins'.",
        )


class OperationConflictError(BuildError):
    """Two handlers are registered for the same path and method (or webhook)."""

    code = 'operation-conflict'


class DuplicateOperationIdError(BuildError):
    """Two operations resolved to the same ``operationId``."""

    code = 'duplicate-operation-id'


class ComponentConflictError(BuildError):
    """Two different schemas want the same component name."""

    code = 'component-conflict'


class UnsupportedSchemaError(BuildError):
    """No schema provider can turn the object into a schema.

    ``target`` is the object; ``location`` is the path to it inside a raw
    schema (``('properties', 'origin')``), empty when it was passed directly.
    """

    code = 'unsupported-schema'
    target: Any
    location: tuple[str, ...]

    def __init__(
        self,
        message: str,
        *,
        target: Any = None,
        location: Sequence[str] = (),
    ) -> None:
        super().__init__(message)
        self.target = target
        self.location = tuple(location)


class UnsupportedErrorObjectError(BuildError):
    """No error provider can describe the object passed to ``errors``."""

    code = 'unsupported-error'


class UnknownSecuritySchemeError(BuildError):
    """An operation refers to a security scheme the document does not define."""

    code = 'unknown-security-scheme'


class ErrorAnnotationError(BuildError):
    """An error class annotation cannot be evaluated."""

    code = 'error-annotation'


class InvalidDocumentError(BuildError):
    """The built document does not pass ``openapi-spec-validator`` (``validate=True``)."""

    code = 'invalid-document'


class UnsupportedDocumentError(BuildError):
    """An included document has an unsupported version or structure."""

    code = 'unsupported-document'


class DocumentConflictError(BuildError):
    """An included document collides with another source (tags, root fields, path items)."""

    code = 'document-conflict'
