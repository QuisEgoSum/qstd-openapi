"""OpenAPI 3.0: converts JSON Schema 2020-12 into the 3.0 Schema Object subset.

What changes:

- ``type: [X, "null"]`` / ``anyOf: [..., {"type": "null"}]`` -> ``nullable: true``
  (a nullable ``$ref`` becomes ``allOf: [$ref]`` + ``nullable``);
- ``const`` -> one-value ``enum``; ``examples`` -> ``example`` (the first one);
- numeric ``exclusiveMinimum``/``exclusiveMaximum`` -> ``minimum``/``maximum`` +
  boolean flag;
- siblings of ``$ref`` (ignored by 3.0) -> ``allOf: [$ref]`` + siblings;
- ``prefixItems`` -> ``items: {anyOf: [...]}`` (the length limits stay);
- keywords 3.0 does not have (``if``/``then``/``else``, ``contentMediaType``,
  ``unevaluatedProperties``, ``patternProperties``...) are dropped;
- webhooks go to ``x-webhooks``; 3.1-only root/info fields are dropped;
- every operation has ``responses`` (3.0 requires it).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Optional, Union, cast

from qstd_openapi.dialects.base import JsonSchema
from qstd_openapi.markers import File, FileList

_ROOT_ORDER = (
    'openapi',
    'info',
    'servers',
    'paths',
    'components',
    'security',
    'tags',
    'externalDocs',
)
_METHODS = ('get', 'put', 'post', 'delete', 'options', 'head', 'patch', 'trace')
_WEBHOOKS_31 = 'webhooks'
_WEBHOOKS_30 = 'x-webhooks'
_DROPPED = frozenset(
    {
        '$schema',
        '$id',
        '$anchor',
        '$dynamicAnchor',
        '$dynamicRef',
        '$comment',
        '$defs',
        'contentMediaType',
        'contentEncoding',
        'contentSchema',
        'if',
        'then',
        'else',
        'dependentSchemas',
        'dependentRequired',
        'unevaluatedProperties',
        'unevaluatedItems',
        'patternProperties',
        'propertyNames',
        'contains',
        'minContains',
        'maxContains',
        'const',
        'examples',
        'prefixItems',
    },
)
_SUBSCHEMA_LISTS = ('allOf', 'anyOf', 'oneOf')
_SUBSCHEMA_SINGLE = ('items', 'not', 'additionalProperties')
_ANNOTATIONS = (
    'title',
    'description',
    'default',
    'example',
    'deprecated',
    'readOnly',
    'writeOnly',
)


def _is_null(schema: Any) -> bool:
    return (
        isinstance(schema, dict)
        and cast('JsonSchema', schema).get('type') == 'null'
        and len(
            cast('JsonSchema', schema),
        )
        == 1
    )


def convert_schema(schema: Any) -> Any:
    """Convert one JSON Schema 2020-12 schema (recursively) to OpenAPI 3.0."""
    if not isinstance(schema, dict):
        return schema
    source = cast('JsonSchema', schema)
    result: JsonSchema = {}
    nullable = False

    for key, value in source.items():
        if key == 'properties' and isinstance(value, dict):
            result[key] = {
                name: convert_schema(item)
                for name, item in cast('JsonSchema', value).items()
            }
        elif key in _SUBSCHEMA_LISTS and isinstance(value, list):
            items = [item for item in cast('list[object]', value) if not _is_null(item)]
            if len(items) != len(cast('list[object]', value)):
                nullable = True
            if items:
                result[key] = [convert_schema(item) for item in items]
        elif key in _SUBSCHEMA_SINGLE and isinstance(value, dict):
            result[key] = convert_schema(value)
        elif key == 'type' and isinstance(value, list):
            types = [t for t in cast('list[str]', value) if t != 'null']
            nullable = nullable or len(types) != len(cast('list[str]', value))
            if len(types) == 1:
                result['type'] = types[0]
            elif types:
                result['anyOf'] = [{'type': t} for t in types]
        elif key == 'type' and value == 'null':
            nullable = True
        elif key == 'enum' and isinstance(value, list):
            values = cast('list[object]', value)
            if None in values:
                nullable = True
            result['enum'] = [item for item in values if item is not None]
        elif key in ('exclusiveMinimum', 'exclusiveMaximum') and _is_number(value):
            bound = 'minimum' if key == 'exclusiveMinimum' else 'maximum'
            result[bound] = value
            result[key] = True
        elif key not in _DROPPED:
            result[key] = value

    if 'const' in source:
        if source['const'] is None:
            nullable = True
        else:
            result['enum'] = [source['const']]
    examples = source.get('examples')
    if isinstance(examples, list) and examples and 'example' not in result:
        result['example'] = cast('list[object]', examples)[0]
    prefix = source.get('prefixItems')
    if isinstance(prefix, list) and 'items' not in result:
        result['items'] = {
            'anyOf': [convert_schema(item) for item in cast('list[object]', prefix)],
        }

    result = _collapse_single_any_of(result)
    if nullable:
        result = _make_nullable(result)
        if 'allOf' in result and 'default' in result and result['default'] is None:
            # 3.0 validators check ``default: null`` against the referenced
            # (non-nullable) schema; for a nullable reference it is only an annotation.
            del result['default']
    if '$ref' in result and len(result) > 1:
        siblings = {k: v for k, v in result.items() if k != '$ref'}
        result = {'allOf': [{'$ref': result['$ref']}], **siblings}
    return result


def _is_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _collapse_single_any_of(schema: JsonSchema) -> JsonSchema:
    """``{anyOf: [S], title: ...}`` (left after removing ``null``) -> S + annotations."""
    any_of = schema.get('anyOf')
    if not (isinstance(any_of, list) and len(cast('list[object]', any_of)) == 1):
        return schema
    only = cast('JsonSchema', cast('list[object]', any_of)[0])
    rest = {k: v for k, v in schema.items() if k != 'anyOf'}
    if '$ref' in only:
        return {'allOf': [only], **rest}
    if any(key in only for key in rest):
        return schema
    return {**only, **rest}


def _make_nullable(schema: JsonSchema) -> JsonSchema:
    if '$ref' in schema:
        siblings = {k: v for k, v in schema.items() if k != '$ref'}
        return {'allOf': [{'$ref': schema['$ref']}], **siblings, 'nullable': True}
    return {**schema, 'nullable': True}


class OpenAPI30:
    """OpenAPI 3.0.x."""

    def __init__(self, version: str = '3.0.3') -> None:
        if not version.startswith('3.0.'):
            raise ValueError(f'OpenAPI30 cannot produce version {version!r}')
        self._version = version

    @property
    def version(self) -> str:
        return self._version

    def file_schema(
        self,
        marker: Union[File, FileList],
        media_type: Optional[str],  # noqa: ARG002 - 3.0 has no contentMediaType
    ) -> JsonSchema:
        if isinstance(marker, FileList):
            schema: JsonSchema = {
                'type': 'array',
                'items': self.file_schema(File(marker.description), None),
            }
            if marker.max_items is not None:
                schema['maxItems'] = marker.max_items
            return schema
        schema = {'type': 'string', 'format': 'binary'}
        if marker.description:
            schema['description'] = marker.description
        return schema

    def check_document(self, document: Mapping[str, Any]) -> None:
        """3.0 documents are taken as they are; 3.1 ones are converted on output."""
        version = document.get('openapi')
        if not isinstance(version, str) or not version.startswith(('3.0.', '3.1.')):
            raise ValueError(f'document version {version!r} is neither 3.0.x nor 3.1.x')

    def extract_webhooks(self, document: dict[str, Any]) -> dict[str, Any]:
        hooks = cast('dict[str, Any]', document.pop(_WEBHOOKS_30, None) or {})
        hooks.update(cast('dict[str, Any]', document.pop(_WEBHOOKS_31, None) or {}))
        return hooks

    def finalize(
        self,
        document: Mapping[str, Any],
        webhooks: Mapping[str, Mapping[str, Any]],
    ) -> dict[str, Any]:
        fields: dict[str, Any] = {
            key: value
            for key, value in document.items()
            if key not in ('jsonSchemaDialect', _WEBHOOKS_31)
        }
        fields['openapi'] = self._version
        fields['info'] = _info(cast('Mapping[str, Any]', fields.get('info', {})))
        fields['paths'] = {
            path: _path_item(cast('Mapping[str, Any]', item))
            for path, item in cast('Mapping[str, Any]', fields.get('paths', {})).items()
        }
        hooks = {
            **cast('Mapping[str, Any]', document.get(_WEBHOOKS_31, {})),
            **webhooks,
        }
        if hooks:
            fields[_WEBHOOKS_30] = {
                name: _path_item(cast('Mapping[str, Any]', hooks[name]))
                for name in sorted(hooks)
            }
        components = fields.get('components')
        if isinstance(components, dict):
            fields['components'] = _components(cast('Mapping[str, Any]', components))
        ordered = {key: fields[key] for key in _ROOT_ORDER if key in fields}
        ordered.update(
            {key: value for key, value in fields.items() if key not in ordered},
        )
        return ordered


def _info(info: Mapping[str, Any]) -> dict[str, Any]:
    result = {key: value for key, value in info.items() if key != 'summary'}
    license_info = result.get('license')
    if isinstance(license_info, dict):
        result['license'] = {
            k: v
            for k, v in cast('Mapping[str, Any]', license_info).items()
            if k != 'identifier'
        }
    return result


def _convert_schemas_in(value: Any) -> Any:
    """Convert every ``schema`` found under parameters, headers and media types."""
    if isinstance(value, list):
        return [_convert_schemas_in(item) for item in cast('list[object]', value)]
    if not isinstance(value, dict):
        return value
    return {
        key: convert_schema(item) if key == 'schema' else _convert_schemas_in(item)
        for key, item in cast('Mapping[str, Any]', value).items()
    }


def _path_item(item: Mapping[str, Any]) -> dict[str, Any]:
    result = cast('dict[str, Any]', _convert_schemas_in(item))
    for method in _METHODS:
        operation = result.get(method)
        if isinstance(operation, dict) and not cast('Mapping[str, Any]', operation).get(
            'responses',
        ):
            cast('dict[str, Any]', operation)['responses'] = {
                'default': {'description': 'Default response'},
            }
    return result


def _components(components: Mapping[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for section, entries in components.items():
        if section == 'pathItems':  # 3.1 only
            continue
        if section == 'schemas':
            result[section] = {
                name: convert_schema(schema)
                for name, schema in cast('Mapping[str, Any]', entries).items()
            }
        else:
            result[section] = _convert_schemas_in(entries)
    return result
