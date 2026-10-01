from __future__ import annotations

import re

from pathlib import Path

import pytest

import qstd_openapi

from qstd_openapi.dialects import OpenAPI31
from qstd_openapi.markers import File, FileList

PACKAGE = Path(qstd_openapi.__file__).parent
VERSION_SPECIFIC = re.compile(
    r"""['"](3\.[01][.'"]|webhooks|contentMediaType|nullable)""",
)


def test_version_specific_strings_live_only_in_dialects() -> None:
    """Adding OpenAPI 3.0 must not require touching the core (contract: dialect layer)."""
    offenders = [
        f'{path.relative_to(PACKAGE)}:{number}: {line.strip()}'
        for path in sorted(PACKAGE.rglob('*.py'))
        if path.parent.name != 'dialects'
        for number, line in enumerate(path.read_text().splitlines(), 1)
        if VERSION_SPECIFIC.search(line)
    ]
    assert offenders == []


def test_file_schemas() -> None:
    dialect = OpenAPI31()
    assert dialect.file_schema(File(None), '*/*') == {
        'type': 'string',
        'format': 'binary',
    }
    assert dialect.file_schema(File(), 'image/png') == {
        'type': 'string',
        'format': 'binary',
        'contentMediaType': 'image/png',
        'description': 'File',
    }
    assert dialect.file_schema(FileList(2, None), None) == {
        'type': 'array',
        'items': {'type': 'string', 'format': 'binary'},
        'maxItems': 2,
    }


def test_finalize_orders_root_and_places_webhooks() -> None:
    document = OpenAPI31('3.1.1').finalize(
        {'x-ext': 1, 'paths': {}, 'info': {'title': 't', 'version': '1'}},
        {'b.event': {'post': {}}, 'a.event': {'post': {}}},
    )
    assert list(document) == ['openapi', 'info', 'paths', 'webhooks', 'x-ext']
    assert document['openapi'] == '3.1.1'
    assert list(document['webhooks']) == ['a.event', 'b.event']


def test_only_3_1_versions() -> None:
    with pytest.raises(ValueError, match=r'3\.0\.3'):
        OpenAPI31('3.0.3')
