"""Stable JSON and YAML serialization for built OpenAPI documents."""

from __future__ import annotations

import importlib
import json

from collections.abc import Mapping
from typing import Any, Optional, cast


def dumps(
    document: Mapping[str, Any],
    *,
    canonical: bool = False,
    indent: Optional[int] = None,
) -> str:
    """Serialize a document to JSON.

    ``canonical=True`` sorts keys and drops whitespace, so the same inputs
    always give byte-identical output.
    """
    if canonical:
        return json.dumps(
            document,
            ensure_ascii=False,
            sort_keys=True,
            separators=(',', ':'),
        )
    return json.dumps(document, ensure_ascii=False, indent=indent)


def dumps_yaml(document: Mapping[str, Any], *, canonical: bool = False) -> str:
    """Serialize a document to YAML (needs the ``yaml`` extra: PyYAML).

    ``canonical=True`` sorts keys, so the same inputs give identical output.
    """
    try:
        yaml: Any = importlib.import_module('yaml')
    except ImportError as exc:
        raise ImportError(
            'YAML output needs PyYAML: install qstd-openapi[yaml]',
        ) from exc
    return cast(
        str,
        yaml.safe_dump(
            _plain(document),
            sort_keys=canonical,
            allow_unicode=True,
            default_flow_style=False,
        ),
    )


def _plain(value: Any) -> Any:
    """Plain dicts/lists so PyYAML's safe dumper accepts any Mapping/Sequence."""
    if isinstance(value, Mapping):
        return {
            str(k): _plain(v) for k, v in cast('Mapping[object, object]', value).items()
        }
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in cast('list[object]', value)]
    return value
