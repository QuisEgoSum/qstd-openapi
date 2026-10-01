"""Error objects (``errors=[...]``) turned into responses by error providers."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Optional, Protocol

from qstd_openapi.core.schemas import JsonSchema, SchemaContext, SchemaRequest
from qstd_openapi.errors import UnsupportedErrorObjectError, UnsupportedSchemaError
from qstd_openapi.meta.model import StatusCode


@dataclass(frozen=True)
class ErrorResponse:
    status: StatusCode
    schema: Any
    """Anything the schema providers understand, usually a raw dict with ``Ref``."""
    name: Optional[str] = None
    """Component name; ``None`` keeps the schema inline."""
    description: Optional[str] = None


class ErrorProvider(Protocol):
    def supports(self, error: object) -> bool: ...

    def describe(self, error: object) -> ErrorResponse: ...


class ErrorSchemas:
    """Adapts error providers to the schema provider protocol.

    Error classes become components, so an error referenced from another
    error's field (a validation error listing item errors) is a ``$ref``.
    """

    def __init__(self, providers: Sequence[ErrorProvider]) -> None:
        self._providers = tuple(providers)

    def provider_for(self, error: object) -> Optional[ErrorProvider]:
        for provider in self._providers:
            if provider.supports(error):
                return provider
        return None

    def describe(self, error: object) -> ErrorResponse:
        provider = self.provider_for(error)
        if provider is None:
            raise UnsupportedErrorObjectError(
                f'No error provider supports {error!r}; pass errors=[...] to OpenAPI '
                '(for example AppErrors from qstd_openapi.contrib.app_errors).',
            )
        return provider.describe(error)

    def supports(self, target: object) -> bool:
        return self.provider_for(target) is not None

    def generate(
        self,
        requests: Sequence[SchemaRequest],
        context: SchemaContext,
    ) -> Sequence[JsonSchema]:
        results: list[JsonSchema] = []
        for request in requests:
            response = self.describe(request.target)
            try:
                schema = context.resolve(response.schema, 'serialization')
            except UnsupportedSchemaError as exc:
                raise _unsupported_field(request.target, exc) from None
            if response.name:
                origin = f'error provider for {request.target!r}'
                schema = context.add_component(response.name, schema, origin)
            results.append(schema)
        return results


def _unsupported_field(
    error: object,
    exc: UnsupportedSchemaError,
) -> UnsupportedSchemaError:
    name = getattr(error, '__qualname__', None) or repr(error)
    location = exc.location
    if len(location) == 2 and location[0] == 'properties':
        where = f'field {location[1]!r}'
        hint = (
            ' If the field is not part of the error response, keep it out of the '
            f'schema: AppErrors skips private (_{location[1]}) and ClassVar fields; '
            'for another rule subclass AppErrors or implement ErrorProvider.'
        )
    else:
        where = '/'.join(location) or 'schema'
        hint = ''
    return UnsupportedSchemaError(
        f'Cannot describe error {name}: no schema provider supports '
        f'{exc.target!r} in its {where}.{hint}',
        target=exc.target,
        location=exc.location,
    )
