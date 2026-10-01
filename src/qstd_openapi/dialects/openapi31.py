"""The default OpenAPI 3.1 dialect."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Optional, Union, cast

from qstd_openapi.dialects.base import JsonSchema
from qstd_openapi.markers import File, FileList

_ROOT_ORDER = (
    'openapi',
    'info',
    'jsonSchemaDialect',
    'servers',
    'paths',
    'webhooks',
    'components',
    'security',
    'tags',
    'externalDocs',
)


class OpenAPI31:
    """OpenAPI 3.1: schemas are JSON Schema 2020-12 as they are."""

    def __init__(self, version: str = '3.1.0') -> None:
        if not version.startswith('3.1.'):
            raise ValueError(f'OpenAPI31 cannot produce version {version!r}')
        self._version = version

    @property
    def version(self) -> str:
        return self._version

    def file_schema(
        self,
        marker: Union[File, FileList],
        media_type: Optional[str],
    ) -> JsonSchema:
        if isinstance(marker, FileList):
            schema: JsonSchema = {
                'type': 'array',
                'items': self.file_schema(File(marker.description), None),
            }
            if marker.max_items is not None:
                schema['maxItems'] = marker.max_items
            return schema
        # ``format: binary`` is an annotation in 3.1 but still what UIs look for.
        schema = {'type': 'string', 'format': 'binary'}
        if media_type and '*' not in media_type:
            schema['contentMediaType'] = media_type
        if marker.description:
            schema['description'] = marker.description
        return schema

    def check_document(self, document: Mapping[str, Any]) -> None:
        version = document.get('openapi')
        if not isinstance(version, str) or not version.startswith('3.1.'):
            raise ValueError(
                f'document version {version!r} is not 3.1.x; convert it first',
            )

    def extract_webhooks(self, document: dict[str, Any]) -> dict[str, Any]:
        return cast('dict[str, Any]', document.pop('webhooks', None) or {})

    def finalize(
        self,
        document: Mapping[str, Any],
        webhooks: Mapping[str, Mapping[str, Any]],
    ) -> dict[str, Any]:
        fields: dict[str, Any] = {**document, 'openapi': self._version}
        if webhooks:
            fields['webhooks'] = {
                name: dict(webhooks[name]) for name in sorted(webhooks)
            }
        ordered = {key: fields[key] for key in _ROOT_ORDER if key in fields}
        ordered.update(
            {key: value for key, value in fields.items() if key not in ordered},
        )
        return ordered
