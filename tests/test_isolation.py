"""The library keeps no mutable state at module level and imports no frameworks."""

from __future__ import annotations

import importlib
import importlib.util
import pkgutil
import subprocess
import sys

import qstd_openapi

MUTABLE = (dict, list, set, bytearray)


OPTIONAL = {
    'qstd_openapi.pydantic': 'pydantic',
    'qstd_openapi.sanic': 'sanic',
    'qstd_openapi.fastapi': 'fastapi',
}


def _modules() -> list[str]:
    prefix = f'{qstd_openapi.__name__}.'
    submodules = pkgutil.walk_packages(qstd_openapi.__path__, prefix)
    names = [qstd_openapi.__name__, *(info.name for info in submodules)]
    return [
        name
        for name in names
        if name not in OPTIONAL or importlib.util.find_spec(OPTIONAL[name]) is not None
    ]


def test_no_module_level_mutable_state() -> None:
    offenders: list[str] = []
    for name in _modules():
        module = importlib.import_module(name)
        for attr, value in vars(module).items():
            if attr.startswith('__'):
                continue
            if isinstance(value, MUTABLE):
                offenders.append(f'{name}.{attr}')
    assert offenders == []


def test_import_does_not_pull_frameworks() -> None:
    code = (
        'import sys, qstd_openapi, qstd_openapi.openapi, qstd_openapi.meta;'
        "heavy = {'pydantic', 'sanic', 'fastapi', 'starlette', 'yaml'};"
        'print(sorted(heavy & set(sys.modules)))'
    )
    result = subprocess.run(
        [sys.executable, '-c', code],
        capture_output=True,
        text=True,
        check=True,
        env={'PYTHONPATH': ':'.join(sys.path)},
    )
    assert result.stdout.strip() == '[]'
