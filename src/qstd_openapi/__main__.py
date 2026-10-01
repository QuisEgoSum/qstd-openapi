"""Command line: ``python -m qstd_openapi dump package.module:spec``.

``TARGET`` is ``module:attribute`` (dotted attributes allowed); the attribute
is an ``OpenAPI`` instance or a function without arguments returning one —
the place to create the application and include its routes.

Options: ``-o FILE`` (stdout by default), ``--yaml`` (also chosen by a
``.yaml``/``.yml`` file name), ``--dialect`` (a version accepted by
``qstd_openapi.dialects.dialect_for``), and ``--check`` (compare with ``FILE``
instead of writing it; exit code 1 and a diff on mismatch).
Errors while loading or building exit with code 2.
"""

from __future__ import annotations

import argparse
import importlib
import os
import sys

from pathlib import Path
from typing import Any, Optional

from qstd_openapi.core.document import OpenAPI
from qstd_openapi.dialects import VERSIONS, dialect_for
from qstd_openapi.errors import QstdOpenAPIError
from qstd_openapi.testing import diff, render


def load(target: str) -> OpenAPI:
    """Resolve ``module:attribute`` to an ``OpenAPI`` (calling a factory)."""
    module_name, _, attribute = target.partition(':')
    if not module_name or not attribute:
        raise ValueError(f'Expected module:attribute, got {target!r}')
    if os.getcwd() not in sys.path:
        sys.path.insert(0, os.getcwd())
    value: Any = importlib.import_module(module_name)
    for part in attribute.split('.'):
        value = getattr(value, part)
    if not isinstance(value, OpenAPI) and callable(value):
        value = value()
    if not isinstance(value, OpenAPI):
        raise TypeError(f'{target} is {type(value).__name__}, not OpenAPI')
    return value


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog='python -m qstd_openapi')
    commands = parser.add_subparsers(dest='command', required=True)
    dump = commands.add_parser('dump', help='build a document and write it')
    dump.add_argument('target', help='module:attribute — OpenAPI or a factory')
    dump.add_argument('-o', '--output', help='file to write (default: stdout)')
    dump.add_argument('--yaml', action='store_true', help='YAML instead of JSON')
    dump.add_argument('--dialect', choices=VERSIONS, help='OpenAPI version')
    dump.add_argument(
        '--check',
        action='store_true',
        help='compare with --output instead of writing; exit 1 on difference',
    )
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    args = _parser().parse_args(argv)
    output = Path(args.output) if args.output else None
    if args.check and output is None:
        sys.stderr.write('error: --check requires -o FILE\n')
        return 2
    yaml = bool(args.yaml) or (
        output is not None and output.suffix in ('.yaml', '.yml')
    )
    try:
        spec = load(args.target)
        if args.dialect:
            spec = spec.derive(dialect=dialect_for(args.dialect))
        text = render(spec, yaml=yaml)
    except (
        QstdOpenAPIError,
        ImportError,
        AttributeError,
        TypeError,
        ValueError,
    ) as exc:
        sys.stderr.write(f'error: {exc}\n')
        return 2
    if args.check:
        assert output is not None
        expected = output.read_text(encoding='utf-8') if output.exists() else ''
        if expected != text:
            sys.stderr.write(f'{output} is out of date\n')
            sys.stderr.write(diff(expected, text, name=str(output)))
            return 1
        return 0
    if output is None:
        sys.stdout.write(text)
    else:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(text, encoding='utf-8')
    return 0


if __name__ == '__main__':  # pragma: no cover - entry point
    sys.exit(main())
