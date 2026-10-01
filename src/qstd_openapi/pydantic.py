"""Schemas from Pydantic models, dataclasses and annotated types.

Install with ``qstd-openapi[pydantic]`` (Pydantic 2) or
``qstd-openapi[pydantic-v1]`` (Pydantic 1.10). Models written against the v1
API inside Pydantic 2 (``pydantic.v1``) are supported as well.

Pydantic 1 support is **experimental** and is expected to be removed in a
future release. Pydantic 1 produces older JSON Schema; its output is
normalized to what Pydantic 2 would produce: ``definitions`` become components, ``Optional``
fields allow ``null``, single-value ``Literal`` becomes ``const`` and enums
get a ``type`` without the boilerplate description.
"""

from __future__ import annotations

import copy
import dataclasses
import datetime
import decimal
import importlib
import uuid

from collections.abc import Iterator, Mapping, Sequence
from types import MappingProxyType
from typing import Any, Callable, Optional, cast, get_args

from qstd_openapi._compat import is_class
from qstd_openapi.core.schemas import (
    JsonSchema,
    OverrideWithin,
    SchemaContext,
    SchemaMode,
    SchemaRequest,
)

__all__ = ('PydanticSchemas',)


def _load() -> tuple[Optional[Any], Optional[Any]]:
    """``(pydantic v2 module or None, v1 API module or None)``."""
    try:
        pydantic: Any = importlib.import_module('pydantic')
    except ImportError as exc:  # pragma: no cover - extra not installed
        raise ImportError(
            'qstd_openapi.pydantic needs Pydantic: install qstd-openapi[pydantic] '
            'or qstd-openapi[pydantic-v1]',
        ) from exc
    if str(pydantic.VERSION).startswith('1.'):
        return None, pydantic
    try:
        v1: Any = importlib.import_module('pydantic.v1')
    except ImportError:  # pragma: no cover - very old 2.x
        v1 = None
    return pydantic, v1


class PydanticSchemas:
    """Schema provider backed by Pydantic.

    Accepts models, dataclasses, any type ``TypeAdapter`` understands and a
    ready ``TypeAdapter`` instance (Pydantic 2). ``by_alias`` controls whether
    field aliases or attribute names are used as property names; it should
    match how the application serializes data.
    """

    def __init__(self, *, by_alias: bool = True) -> None:
        self._v2, self._v1 = _load()
        self.by_alias = by_alias
        self._supported: dict[Any, bool] = {}

    # --- protocol -------------------------------------------------------

    def supports(self, target: object) -> bool:
        try:
            key: Any = target
            hash(key)
        except TypeError:
            return False
        if key not in self._supported:
            self._supported[key] = self._check(target)
        return self._supported[key]

    def generate(
        self,
        requests: Sequence[SchemaRequest],
        context: SchemaContext,
    ) -> Sequence[JsonSchema]:
        results: list[Optional[JsonSchema]] = [None] * len(requests)
        v2_indexes = [i for i, r in enumerate(requests) if not self._is_v1(r.target)]
        if v2_indexes:
            for index, schema in zip(
                v2_indexes,
                self._generate_v2([requests[i] for i in v2_indexes], context),
            ):
                results[index] = schema
        for index, request in enumerate(requests):
            if results[index] is None:
                results[index] = self._generate_v1(
                    request.target,
                    request.mode,
                    context,
                )
        return cast('list[JsonSchema]', results)

    # --- detection ------------------------------------------------------

    def _is_v1(self, target: object) -> bool:
        """Whether ``target`` (or a type inside ``List[...]`` etc.) uses the v1 API."""
        if self._v1 is None:
            return False
        if self._v2 is None:
            return True
        if is_class(target) and issubclass(target, self._v1.BaseModel):
            return True
        return any(self._is_v1(arg) for arg in get_args(target))

    def _is_adapter(self, target: object) -> bool:
        return self._v2 is not None and isinstance(target, self._v2.TypeAdapter)

    def _check(self, target: object) -> bool:
        if isinstance(target, Mapping):
            return False
        if self._is_adapter(target):
            return True
        try:
            if self._is_v1(target):
                self._v1_schema_of(target, '#/{model}')
            else:
                assert self._v2 is not None
                self._v2.TypeAdapter(target)
        except Exception:
            return False
        return True

    # --- Pydantic 2 -----------------------------------------------------

    def _generate_v2(
        self,
        requests: Sequence[SchemaRequest],
        context: SchemaContext,
    ) -> list[JsonSchema]:
        assert self._v2 is not None
        adapter = self._v2.TypeAdapter
        generator = _override_generator(self._v2, context.type_override)
        inputs = [
            (
                index,
                r.mode,
                r.target if self._is_adapter(r.target) else adapter(r.target),
            )
            for index, r in enumerate(requests)
        ]
        keys, definitions = adapter.json_schemas(
            inputs,
            by_alias=self.by_alias,
            ref_template=context.ref_template,
            schema_generator=generator,
        )
        for name, schema in cast(
            'Mapping[str, JsonSchema]',
            definitions.get('$defs', {}),
        ).items():
            context.add_component(name, schema, 'PydanticSchemas')
        return [
            cast('JsonSchema', keys[(index, r.mode)])
            for index, r in enumerate(requests)
        ]

    # --- Pydantic 1 -----------------------------------------------------

    def _v1_schema_of(self, target: Any, ref_template: str) -> JsonSchema:
        """A private copy: Pydantic 1 caches ``Model.schema()`` and we edit the result."""
        assert self._v1 is not None
        if is_class(target) and issubclass(target, self._v1.BaseModel):
            schema = cast(Any, target).schema(
                by_alias=self.by_alias,
                ref_template=ref_template,
            )
        else:
            schema = self._v1.schema_of(
                target,
                by_alias=self.by_alias,
                ref_template=ref_template,
            )
        return cast('JsonSchema', copy.deepcopy(schema))

    def _generate_v1(
        self,
        target: Any,
        mode: SchemaMode,
        context: SchemaContext,
    ) -> JsonSchema:
        assert self._v1 is not None
        schema = self._v1_schema_of(target, context.ref_template)
        definitions = cast('dict[str, JsonSchema]', schema.pop('definitions', {}))
        is_model = is_class(target) and issubclass(target, self._v1.BaseModel)
        if is_model:
            name = target.__name__
            definitions[name] = schema
            result: JsonSchema = {'$ref': context.ref_template.format(model=name)}
        else:
            schema.pop('title', None)  # "ParsingModel[...]" wrapper title
            result = {'$ref': schema['$ref']} if '$ref' in schema else schema

        changed: set[str] = set()
        for model in _v1_models(target, self._v1):
            definition = definitions.get(model.__name__)
            if definition is not None:
                if self._v1_overrides(model, definition, mode, context):
                    changed.add(model.__name__)
                self._v1_nullable(model, definition)
        if changed:
            result = _v1_mode_variants(definitions, result, changed, mode, context)
        for name, definition in definitions.items():
            context.add_component(
                name,
                _v1_normalize(definition, root=True),
                'PydanticSchemas',
            )
        return _v1_normalize(result, root=False)

    def _v1_overrides(
        self,
        model: Any,
        definition: JsonSchema,
        mode: SchemaMode,
        context: SchemaContext,
    ) -> bool:
        """Apply ``type_overrides`` to the fields of one class.

        Covers fields of the overridden type itself, its sequences and dict
        values (``Optional`` is restored by ``_v1_nullable`` afterwards).
        Returns whether a mode-specific override changed the definition.
        """
        assert self._v1 is not None
        within: OverrideWithin = (
            'models' if issubclass(model, self._v1.BaseModel) else 'dataclasses'
        )
        properties = cast('dict[str, JsonSchema]', definition.get('properties', {}))
        mode_specific = False
        for field in _v1_fields(model).values():
            key = field.alias if self.by_alias else field.name
            prop = properties.get(key)
            override = context.type_override(field.type_, mode, within)
            if prop is None or override is None:
                continue
            if field.shape == _V1_SINGLETON:
                meta = {k: prop[k] for k in _V1_FIELD_META if k in prop}
                properties[key] = {**override, **meta}
            elif field.shape in _V1_SEQUENCES and 'items' in prop:
                prop['items'] = override
            elif field.shape in _V1_MAPPINGS and 'additionalProperties' in prop:
                prop['additionalProperties'] = override
            else:
                continue
            mode_specific = mode_specific or (
                context.type_override(field.type_, _other(mode), within) != override
            )
        return mode_specific

    def _v1_nullable(self, model: Any, definition: JsonSchema) -> None:
        """Pydantic 1 drops ``null`` from ``Optional`` fields; put it back."""
        properties = cast('dict[str, JsonSchema]', definition.get('properties', {}))
        for field in _v1_fields(model).values():
            key = field.alias if self.by_alias else field.name
            prop = properties.get(key)
            if prop is None or not field.allow_none:
                continue
            meta = {
                k: prop.pop(k) for k in ('title', 'description', 'default') if k in prop
            }
            if not field.required and field.default is None:
                meta['default'] = None
            properties[key] = {'anyOf': [prop, {'type': 'null'}], **meta}


_V1_SINGLETON = 1
_V1_SEQUENCES = frozenset({2, 3, 6, 7, 8, 11})
"""``ModelField.shape``: list, set, tuple-ellipsis, sequence, frozenset, deque."""
_V1_MAPPINGS = frozenset({4, 12, 13})
"""``ModelField.shape``: mapping, dict, defaultdict."""
_V1_FIELD_META = ('title', 'description', 'default')


def _other(mode: SchemaMode) -> SchemaMode:
    return 'serialization' if mode == 'validation' else 'validation'


def _v1_mode_variants(
    definitions: dict[str, JsonSchema],
    result: JsonSchema,
    changed: set[str],
    mode: SchemaMode,
    context: SchemaContext,
) -> JsonSchema:
    """Rename definitions a mode-specific override changed, as Pydantic 2 does.

    Pydantic 1 has a single schema per class; when an override applies only to
    requests or only to responses the class gets ``-Input``/``-Output``, and so
    does every definition referring to it.
    """
    refs = {name: context.ref_template.format(model=name) for name in definitions}

    def refers(value: Any, names: set[str]) -> bool:
        if isinstance(value, dict):
            items = cast('JsonSchema', value)
            ref = items.get('$ref')
            if any(ref == refs[name] for name in names):
                return True
            return any(refers(item, names) for item in items.values())
        if isinstance(value, list):
            return any(refers(item, names) for item in cast('list[object]', value))
        return False

    grown = True
    while grown:
        grown = False
        for name, definition in definitions.items():
            if name not in changed and refers(definition, changed):
                changed.add(name)
                grown = True
    suffix = '-Input' if mode == 'validation' else '-Output'
    renamed = {
        refs[name]: context.ref_template.format(model=f'{name}{suffix}')
        for name in changed
    }

    def rewrite(value: Any) -> Any:
        if isinstance(value, dict):
            items = cast('JsonSchema', value)
            return {
                key: (
                    renamed.get(item, item)
                    if key == '$ref' and isinstance(item, str)
                    else rewrite(item)
                )
                for key, item in items.items()
            }
        if isinstance(value, list):
            return [rewrite(item) for item in cast('list[object]', value)]
        return value

    for name in list(definitions):
        definition = cast('JsonSchema', rewrite(definitions.pop(name)))
        definitions[f'{name}{suffix}' if name in changed else name] = definition
    return cast('JsonSchema', rewrite(result))


_CORE_TYPES: Mapping[str, type] = MappingProxyType(
    {
        'str': str,
        'int': int,
        'float': float,
        'bool': bool,
        'bytes': bytes,
        'decimal': decimal.Decimal,
        'datetime': datetime.datetime,
        'date': datetime.date,
        'time': datetime.time,
        'timedelta': datetime.timedelta,
        'uuid': uuid.UUID,
    },
)


def _scalar_target(schema: Mapping[str, Any]) -> Optional[type]:
    """The scalar Python type a Pydantic core schema stands for, if known."""
    core_type = schema.get('type')
    return _CORE_TYPES.get(core_type) if isinstance(core_type, str) else None


TypeOverrideLookup = Callable[
    [Any, SchemaMode, Optional[OverrideWithin]],
    Optional[JsonSchema],
]


def _override_generator(v2: Any, lookup: TypeOverrideLookup) -> Any:
    """A ``GenerateJsonSchema`` applying the document's ``type_overrides``.

    Keeps a stack of the classes being described, so an override limited to
    model or dataclass fields knows whose field it is looking at.
    """
    base: Any = importlib.import_module(f'{v2.__name__}.json_schema').GenerateJsonSchema

    class _Generator(base):  # type: ignore[misc, valid-type]
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            parent: Any = super()
            parent.__init__(*args, **kwargs)
            self._within: list[OverrideWithin] = []

        def _lookup(self, target: Any) -> Optional[JsonSchema]:
            within = self._within[-1] if self._within else None
            return lookup(target, self.mode, within)

        def _class_schema(self, method: str, within: Any, schema: Any) -> Any:
            # The body of the class's definition: Pydantic still registers it
            # under its name, so references to it stay valid.
            override = self._lookup(schema.get('cls'))
            if override is not None:
                return override
            parent: Any = super()
            if within is not None:
                self._within.append(within)
            try:
                return getattr(parent, method)(schema)
            finally:
                if within is not None:
                    self._within.pop()

        def model_schema(self, schema: Any) -> Any:
            return self._class_schema('model_schema', 'models', schema)

        def dataclass_schema(self, schema: Any) -> Any:
            return self._class_schema('dataclass_schema', 'dataclasses', schema)

        def enum_schema(self, schema: Any) -> Any:
            return self._class_schema('enum_schema', None, schema)

        def generate_inner(self, schema: Any) -> Any:
            target = _scalar_target(schema)
            if target is not None:
                override = self._lookup(target)
                if override is not None:
                    return override
            parent: Any = super()
            return parent.generate_inner(schema)

    return _Generator


def _v1_fields(model: Any) -> Mapping[str, Any]:
    inner = getattr(model, '__pydantic_model__', model)
    return cast('Mapping[str, Any]', getattr(inner, '__fields__', {}))


def _v1_models(target: Any, v1: Any) -> Iterator[Any]:
    """Model and dataclass classes reachable from ``target``."""
    seen: set[int] = set()
    stack: list[Any] = [target]
    while stack:
        current = stack.pop()
        if id(current) in seen:
            continue
        seen.add(id(current))
        if is_class(current) and (
            issubclass(current, v1.BaseModel) or dataclasses.is_dataclass(current)
        ):
            yield current
            for field in _v1_fields(current).values():
                stack.append(field.outer_type_)
                stack.append(field.type_)
        stack.extend(get_args(current))


def _v1_normalize(schema: JsonSchema, *, root: bool) -> JsonSchema:
    """Bring Pydantic 1 output closer to Pydantic 2 (JSON Schema 2020-12)."""
    result: JsonSchema = {}
    for key, value in schema.items():
        if isinstance(value, dict):
            result[key] = _v1_normalize(cast('JsonSchema', value), root=False)
        elif isinstance(value, list):
            result[key] = [
                (
                    _v1_normalize(cast('JsonSchema', item), root=False)
                    if isinstance(item, dict)
                    else item
                )
                for item in cast('list[object]', value)
            ]
        else:
            result[key] = value
    enum_values = result.get('enum')
    if isinstance(enum_values, list):
        values = cast('list[object]', enum_values)
        if root:
            if result.get('description') == 'An enumeration.':
                del result['description']
            if (
                'type' not in result
                and values
                and all(isinstance(v, str) for v in values)
            ):
                result['type'] = 'string'
            elif (
                'type' not in result
                and values
                and all(isinstance(v, int) for v in values)
            ):
                result['type'] = 'integer'
        elif len(values) == 1:
            result['const'] = values[0]
            del result['enum']
    return result
