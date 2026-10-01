"""Turning schema references into JSON Schema 2020-12.

Providers are asked in batches: while operations are rendered every schema
reference becomes a placeholder, and only when everything has been seen are
the providers run. That lets a provider such as Pydantic see all models at
once and name input/output variants consistently. Placeholders are then
replaced in the whole document.
"""

from __future__ import annotations

import copy
import dataclasses
import datetime
import decimal
import enum
import sys
import uuid

from collections.abc import Mapping, Sequence
from types import MappingProxyType
from typing import (
    TYPE_CHECKING,
    Annotated,
    Any,
    Literal,
    Optional,
    Protocol,
    Union,
    cast,
    get_args,
    get_origin,
)

from qstd_openapi._compat import is_class
from qstd_openapi.errors import ComponentConflictError, UnsupportedSchemaError
from qstd_openapi.markers import File, FileList, FormFields, Ref

if TYPE_CHECKING:
    from qstd_openapi.dialects.base import OpenAPIDialect

JsonSchema = dict[str, Any]
SchemaMode = Literal['validation', 'serialization']
REF_TEMPLATE = '#/components/schemas/{model}'


@dataclasses.dataclass(frozen=True)
class SchemaRequest:
    target: Any
    mode: SchemaMode


OverrideWithin = Literal['models', 'dataclasses']
"""Whose fields an override is limited to: Pydantic models or dataclasses."""


@dataclasses.dataclass(frozen=True)
class TypeOverride:
    """A schema used for a Python type instead of the one a provider would give.

    Use it when the application serializes a type differently from what the
    provider assumes (a custom JSON encoder turning ``Decimal`` into a number).

    ``mode`` limits the override to request data (``'validation'``) or to
    responses (``'serialization'``); ``within`` limits it to fields declared in
    Pydantic models (``'models'``) or in dataclasses (``'dataclasses'``).
    ``None`` means everywhere. The schema is plain JSON Schema (no markers).
    """

    schema: Mapping[str, Any]
    mode: Optional[SchemaMode] = None
    within: Optional[OverrideWithin] = None

    def applies(self, mode: SchemaMode, within: Optional[OverrideWithin]) -> bool:
        return (self.mode is None or self.mode == mode) and (
            self.within is None or self.within == within
        )


TypeOverrideValue = Union[Mapping[str, Any], TypeOverride, Sequence[TypeOverride]]
"""A plain schema (everywhere), one override or several (the first that applies)."""


class TypeOverrides:
    """``type_overrides`` of a document, normalized; keys are classes."""

    def __init__(
        self,
        overrides: Optional[Mapping[Any, TypeOverrideValue]] = None,
    ) -> None:
        self._overrides: dict[Any, tuple[TypeOverride, ...]] = {}
        for target, value in (overrides or {}).items():
            if not is_class(target):
                raise TypeError(
                    f'type_overrides keys must be classes, got {target!r}',
                )
            if isinstance(value, TypeOverride):
                items: tuple[TypeOverride, ...] = (value,)
            elif isinstance(value, Mapping):
                items = (TypeOverride(value),)
            else:
                items = tuple(value)
            for item in items:
                if not isinstance(
                    item,
                    TypeOverride,
                ):  # pyright: ignore[reportUnnecessaryIsInstance]
                    raise TypeError(
                        f'type_overrides[{target!r}] must be a schema dict, '
                        f'a TypeOverride or a list of them, got {item!r}',
                    )
            self._overrides[target] = items

    def __bool__(self) -> bool:
        return bool(self._overrides)

    def lookup(
        self,
        target: Any,
        mode: SchemaMode,
        within: Optional[OverrideWithin] = None,
    ) -> Optional[JsonSchema]:
        """A private copy of the schema overriding ``target``, if any applies."""
        try:
            items = self._overrides.get(target, ())
        except TypeError:  # unhashable target
            return None
        for item in items:
            if item.applies(mode, within):
                return copy.deepcopy(dict(item.schema))
        return None


class SchemaContext(Protocol):
    """What a provider may use while generating schemas."""

    @property
    def ref_template(self) -> str: ...

    def type_override(
        self,
        target: Any,
        mode: SchemaMode,
        within: Optional[OverrideWithin] = None,
    ) -> Optional[JsonSchema]:
        """The document's schema for ``target`` when it overrides the provider's.

        ``within`` tells whose field is being described (a model's or a
        dataclass's); ``None`` for a type that is not a field.
        """
        ...

    def resolve(self, target: Any, mode: SchemaMode) -> JsonSchema:
        """Schema (possibly a placeholder) for a nested reference."""
        ...

    def add_component(self, name: str, schema: JsonSchema, origin: str) -> JsonSchema:
        """Register ``components/schemas/<name>`` and return a ``$ref`` to it."""
        ...


class SchemaProvider(Protocol):
    def supports(self, target: object) -> bool: ...

    def generate(
        self,
        requests: Sequence[SchemaRequest],
        context: SchemaContext,
    ) -> Sequence[JsonSchema]:
        """One schema per request, in the same order."""
        ...


class Components:
    """``components/schemas`` with strict name-conflict detection."""

    def __init__(self) -> None:
        self._schemas: dict[str, tuple[JsonSchema, str]] = {}

    def add(self, name: str, schema: JsonSchema, origin: str) -> None:
        existing = self._schemas.get(name)
        if existing is None:
            self._schemas[name] = (schema, origin)
            return
        if existing[0] != schema:
            raise ComponentConflictError(
                f'Component schema {name!r} is defined differently by {existing[1]} '
                f'and {origin}. Rename one of the models.',
            )

    def get(self, name: str) -> Optional[JsonSchema]:
        item = self._schemas.get(name)
        return item[0] if item else None

    def replace_all(self, schemas: Mapping[str, JsonSchema]) -> None:
        for name, schema in schemas.items():
            self._schemas[name] = (schema, self._schemas[name][1])

    def keep(self, names: set[str]) -> None:
        self._schemas = {k: v for k, v in self._schemas.items() if k in names}

    def as_dict(self) -> dict[str, JsonSchema]:
        return {name: self._schemas[name][0] for name in sorted(self._schemas)}


class _Pending:
    """Placeholder inserted into the document until the provider has run.

    Compared by identity, so schemas holding different placeholders are
    never mistaken for equal ones.
    """

    __slots__ = ('provider', 'request', 'result')

    def __init__(self, provider: SchemaProvider, request: SchemaRequest) -> None:
        self.provider = provider
        self.request = request
        self.result: Optional[JsonSchema] = None

    def __copy__(self) -> _Pending:
        return self

    def __deepcopy__(self, memo: dict[int, Any]) -> _Pending:
        return self


def _key(target: Any) -> Any:
    try:
        hash(target)
    except TypeError:
        return ('id', id(target))
    return target


class SchemaResolver:
    def __init__(
        self,
        providers: Sequence[SchemaProvider],
        dialect: OpenAPIDialect,
        components: Components,
        ref_template: str = REF_TEMPLATE,
        type_overrides: Optional[TypeOverrides] = None,
    ) -> None:
        self._providers = list(providers)
        self._dialect = dialect
        self.components = components
        self._ref_template = ref_template
        self._overrides = type_overrides or TypeOverrides()
        self._pending: dict[tuple[int, Any, str], _Pending] = {}
        self._queue: list[_Pending] = []

    @property
    def ref_template(self) -> str:
        return self._ref_template

    def type_override(
        self,
        target: Any,
        mode: SchemaMode,
        within: Optional[OverrideWithin] = None,
    ) -> Optional[JsonSchema]:
        return self._overrides.lookup(target, mode, within)

    def ref(self, name: str) -> JsonSchema:
        return {'$ref': self._ref_template.format(model=name)}

    def component_name(self, ref: str) -> Optional[str]:
        prefix, _, suffix = self._ref_template.partition('{model}')
        if ref.startswith(prefix) and ref.endswith(suffix):
            return ref[len(prefix) : len(ref) - len(suffix)]
        return None

    def add_component(self, name: str, schema: JsonSchema, origin: str) -> JsonSchema:
        self.components.add(name, schema, origin)
        return self.ref(name)

    def resolve(
        self,
        target: Any,
        mode: SchemaMode,
        provider: Optional[SchemaProvider] = None,
    ) -> JsonSchema:
        if provider is None:
            if isinstance(target, Mapping):
                return self._resolve_raw(cast('Mapping[str, Any]', target), mode)
            if isinstance(target, Ref):
                return self.resolve(
                    target.target,
                    cast('SchemaMode', target.mode or mode),
                )
            if isinstance(target, (File, FileList)):
                return self._dialect.file_schema(target, None)
            if isinstance(target, FormFields):
                return self._form(target, mode)
            override = self._overrides.lookup(target, mode)
            if override is not None:
                return override
            provider = self._provider_for(target)
        key = (id(provider), _key(target), mode)
        pending = self._pending.get(key)
        if pending is None:
            pending = _Pending(provider, SchemaRequest(target, mode))
            if isinstance(provider, BuiltinSchemas):
                # Built-in schemas need no batching. Resolve them immediately so
                # an unsupported nested type fails while its context is still known.
                pending.result = provider.generate([pending.request], self)[0]
            else:
                self._queue.append(pending)
            self._pending[key] = pending
        return cast('JsonSchema', pending)

    def content_schema(
        self,
        targets: Sequence[Any],
        media_type: str,
        mode: SchemaMode,
        provider: Optional[SchemaProvider] = None,
    ) -> JsonSchema:
        """Schema of one media type; several targets become ``oneOf``."""
        schemas = [
            (
                self._dialect.file_schema(target, media_type)
                if isinstance(target, (File, FileList))
                else self.resolve(target, mode, provider)
            )
            for target in targets
        ]
        return schemas[0] if len(schemas) == 1 else {'oneOf': schemas}

    def _provider_for(self, target: Any) -> SchemaProvider:
        for provider in self._providers:
            if provider.supports(target):
                return provider
        hint = (
            ' A list is not a schema: for alternatives use body_one_of(A, B), '
            'responses(A, B) or responses={status: [A, B]}; for an array use list[A].'
            if isinstance(target, (list, tuple))
            else ' Install the pydantic extra, pass a raw JSON Schema dict or add a '
            'SchemaProvider.'
        )
        raise UnsupportedSchemaError(
            f'No schema provider supports {target!r}.{hint}',
            target=target,
        )

    def _resolve_raw(self, schema: Mapping[str, Any], mode: SchemaMode) -> JsonSchema:
        def walk(value: Any, path: tuple[str, ...]) -> Any:
            if isinstance(value, (Ref, File, FileList, FormFields)):
                try:
                    return self.resolve(value, mode)
                except UnsupportedSchemaError as exc:
                    if exc.location:
                        raise
                    raise UnsupportedSchemaError(
                        f'{exc} (at {"/".join(path)})',
                        target=exc.target,
                        location=path,
                    ) from None
            if isinstance(value, Mapping):
                items = cast('Mapping[str, Any]', value).items()
                return {k: walk(v, (*path, str(k))) for k, v in items}
            if isinstance(value, (list, tuple)):
                values = cast('Sequence[Any]', value)
                return [walk(v, (*path, str(i))) for i, v in enumerate(values)]
            return value

        return cast('JsonSchema', walk(schema, ()))

    def _form(self, form: FormFields, mode: SchemaMode) -> JsonSchema:
        schema: JsonSchema = {
            'type': 'object',
            'properties': {
                name: self.resolve(value, mode) for name, value in form.fields
            },
        }
        if form.required:
            schema['required'] = list(form.required)
        if form.description:
            schema['description'] = form.description
        return schema

    def run(self) -> None:
        """Run providers until no placeholders are waiting (providers may nest)."""
        while self._queue:
            queue, self._queue = self._queue, []
            by_provider: dict[int, list[_Pending]] = {}
            for pending in queue:
                by_provider.setdefault(id(pending.provider), []).append(pending)
            for group in by_provider.values():
                provider = group[0].provider
                results = provider.generate([p.request for p in group], self)
                if len(results) != len(group):
                    raise RuntimeError(
                        f'{type(provider).__name__}.generate returned {len(results)} '
                        f'schemas for {len(group)} requests',
                    )
                for pending, result in zip(group, results):
                    pending.result = result

    def fill(self, value: Any) -> Any:
        """Replace placeholders inside ``value`` in place; returns the filled value.

        Provider results are deep-copied on insertion, so no two places in the
        document share a mutable schema object.
        """
        if isinstance(value, _Pending):
            if value.result is None:
                raise RuntimeError('schema placeholder was never resolved; call run()')
            return self.fill(copy.deepcopy(value.result))
        if isinstance(value, dict):
            mapping = cast('JsonSchema', value)
            for key, item in mapping.items():
                mapping[key] = self.fill(item)
        elif isinstance(value, list):
            items = cast('list[object]', value)
            for index, item in enumerate(items):
                items[index] = self.fill(item)
        return cast(Any, value)

    def finish(self) -> None:
        """Run the providers and fill placeholders inside component schemas."""
        self.run()
        self.components.replace_all(
            {
                name: self.fill(schema)
                for name, schema in self.components.as_dict().items()
            },
        )


# --- built-in provider -------------------------------------------------------

_SIMPLE: Mapping[Any, JsonSchema] = MappingProxyType(
    {
        str: {'type': 'string'},
        int: {'type': 'integer'},
        float: {'type': 'number'},
        bool: {'type': 'boolean'},
        bytes: {'type': 'string', 'format': 'binary'},
        type(None): {'type': 'null'},
        datetime.datetime: {'type': 'string', 'format': 'date-time'},
        datetime.date: {'type': 'string', 'format': 'date'},
        datetime.time: {'type': 'string', 'format': 'time'},
        datetime.timedelta: {'type': 'string', 'format': 'duration'},
        uuid.UUID: {'type': 'string', 'format': 'uuid'},
    },
)

_UNION_TYPES: tuple[Any, ...] = (Union,)
if sys.version_info >= (3, 10):  # pragma: no cover - depends on interpreter
    import types

    _UNION_TYPES = (Union, types.UnionType)


class BuiltinSchemas:
    """Plain Python types, enums and ``typing`` constructs, without Pydantic.

    Used last: when Pydantic is installed it handles everything it supports.
    """

    def supports(self, target: object) -> bool:
        try:
            hash(target)
        except TypeError:
            return False
        if target is Any or target in _SIMPLE or target is decimal.Decimal:
            return True
        if is_class(target) and issubclass(target, enum.Enum):
            return True
        origin = get_origin(target)
        return origin is not None and (
            origin in _UNION_TYPES
            or origin is Literal
            or origin is Annotated
            or origin in (list, set, frozenset, tuple, dict)
            or origin in (Sequence, Mapping)
        )

    def generate(
        self,
        requests: Sequence[SchemaRequest],
        context: SchemaContext,
    ) -> Sequence[JsonSchema]:
        return [self._schema(r.target, r.mode, context) for r in requests]

    def _schema(
        self,
        target: Any,
        mode: SchemaMode,
        context: SchemaContext,
    ) -> JsonSchema:
        if target is Any:
            return {}
        if target in _SIMPLE:
            return dict(_SIMPLE[target])
        if target is decimal.Decimal:
            if mode == 'serialization':
                return {'type': 'string'}
            return {'anyOf': [{'type': 'number'}, {'type': 'string'}]}
        if is_class(target) and issubclass(target, enum.Enum):
            return self._enum(target, context)
        origin = get_origin(target)
        args = get_args(target)
        if origin is Annotated:
            return context.resolve(args[0], mode)
        if origin is Literal:
            values = list(args)
            if len(values) == 1:
                return {'const': values[0], **_json_type(values)}
            return {'enum': values, **_json_type(values)}
        if origin in _UNION_TYPES:
            return {'anyOf': [context.resolve(arg, mode) for arg in args]}
        if origin is tuple:
            if len(args) == 2 and args[1] is Ellipsis:
                return {'type': 'array', 'items': context.resolve(args[0], mode)}
            return {
                'type': 'array',
                'prefixItems': [context.resolve(arg, mode) for arg in args],
                'minItems': len(args),
                'maxItems': len(args),
            }
        if origin in (dict, Mapping):
            value_type = args[1] if len(args) == 2 else Any
            return {
                'type': 'object',
                'additionalProperties': context.resolve(value_type, mode),
            }
        schema: JsonSchema = {'type': 'array'}
        if args:
            schema['items'] = context.resolve(args[0], mode)
        if origin in (set, frozenset):
            schema['uniqueItems'] = True
        return schema

    @staticmethod
    def _enum(target: type[enum.Enum], context: SchemaContext) -> JsonSchema:
        values = [member.value for member in target]
        schema: JsonSchema = {
            'enum': values,
            'title': target.__name__,
            **_json_type(values),
        }
        return context.add_component(target.__name__, schema, 'BuiltinSchemas')


def _json_type(values: Sequence[Any]) -> JsonSchema:
    if values and all(isinstance(v, str) for v in values):
        return {'type': 'string'}
    if values and all(isinstance(v, bool) for v in values):
        return {'type': 'boolean'}
    if values and all(isinstance(v, int) and not isinstance(v, bool) for v in values):
        return {'type': 'integer'}
    return {}
