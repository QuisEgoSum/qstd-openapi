"""Keeping the built document under version control.

The document is rendered with sorted keys and indentation, so a snapshot
committed next to the code shows every change of the API in review::

    from qstd_openapi.testing import assert_matches_snapshot

    def test_openapi_document() -> None:
        assert_matches_snapshot(build_spec(), 'docs/openapi/users_api.json')

Run the tests with ``QSTD_OPENAPI_UPDATE_SNAPSHOTS=1`` to write (or
rewrite) snapshots after an intended change. The same check without pytest:
``python -m qstd_openapi dump package.module:spec -o docs/openapi.json --check``.
"""

from __future__ import annotations

import difflib
import json
import os

from collections.abc import Mapping
from pathlib import Path
from typing import Any, Optional, Union

from qstd_openapi.core.document import OpenAPI
from qstd_openapi.serialization import dumps_yaml

__all__ = ('UPDATE_ENV', 'assert_matches_snapshot', 'diff', 'render')

UPDATE_ENV = 'QSTD_OPENAPI_UPDATE_SNAPSHOTS'
"""Environment variable that makes :func:`assert_matches_snapshot` write snapshots."""

_MAX_DIFF_LINES = 200

Target = Union[OpenAPI, Mapping[str, Any]]


def render(target: Target, *, yaml: bool = False) -> str:
    """The document of ``target`` (an ``OpenAPI`` or a built document) as stable text."""
    document = target.build().document if isinstance(target, OpenAPI) else target
    if yaml:
        return dumps_yaml(document, canonical=True)
    return json.dumps(document, ensure_ascii=False, sort_keys=True, indent=2) + '\n'


def diff(expected: str, actual: str, *, name: str = 'snapshot') -> str:
    """A unified diff of two rendered documents, cut to a readable length."""
    lines = list(
        difflib.unified_diff(
            expected.splitlines(keepends=True),
            actual.splitlines(keepends=True),
            fromfile=f'{name} (expected)',
            tofile=f'{name} (built)',
        ),
    )
    if len(lines) > _MAX_DIFF_LINES:
        hidden = len(lines) - _MAX_DIFF_LINES
        lines = [*lines[:_MAX_DIFF_LINES], f'... {hidden} more diff lines\n']
    return ''.join(lines)


def assert_matches_snapshot(
    target: Target,
    path: Union[str, os.PathLike[str]],
    *,
    yaml: Optional[bool] = None,
    update: Optional[bool] = None,
) -> None:
    """Fail with a diff when the document differs from the snapshot at ``path``.

    ``yaml`` defaults to the file extension (``.yaml``/``.yml``); ``update``
    defaults to the ``QSTD_OPENAPI_UPDATE_SNAPSHOTS`` environment variable.
    In update mode the snapshot is written and the check passes.
    """
    snapshot = Path(path)
    if yaml is None:
        yaml = snapshot.suffix in ('.yaml', '.yml')
    if update is None:
        update = os.environ.get(UPDATE_ENV, '') not in ('', '0')
    actual = render(target, yaml=yaml)
    if update:
        if not snapshot.exists() or snapshot.read_text(encoding='utf-8') != actual:
            snapshot.parent.mkdir(parents=True, exist_ok=True)
            snapshot.write_text(actual, encoding='utf-8')
        return
    if not snapshot.exists():
        raise AssertionError(
            f'OpenAPI snapshot {snapshot} does not exist; '
            f'run with {UPDATE_ENV}=1 to create it',
        )
    expected = snapshot.read_text(encoding='utf-8')
    if expected != actual:
        raise AssertionError(
            f'OpenAPI document differs from {snapshot}; if the change is '
            f'intended, run with {UPDATE_ENV}=1 to update it.\n'
            + diff(expected, actual, name=str(snapshot)),
        )
